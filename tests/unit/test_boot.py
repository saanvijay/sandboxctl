"""Tests for the full-service boot wiring."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sandbox_ctl import boot
from sandbox_ctl.api.app import AppContext
from sandbox_ctl.boot import (
    BootError,
    _docker_cold_spec_factory,
    _k8s_cold_spec_factory,
    _k8s_pod_name,
    build_app,
    build_context,
)
from sandbox_ctl.config import Settings
from sandbox_ctl.isolation.creds import SessionCredential


def _docker_settings(settings: Settings, signing_key: Path) -> Settings:
    return replace(
        settings,
        runtime_backend="docker",
        creds_signing_key_path=str(signing_key),
    )


def test_docker_backend_returns_wired_app_context(settings: Settings, signing_key: Path) -> None:
    s = _docker_settings(settings, signing_key)
    ctx = build_context(s)
    assert isinstance(ctx, AppContext)
    assert ctx.settings is s
    assert ctx.manager is not None
    assert ctx.registry is not None
    assert ctx.auth is not None


@pytest.mark.asyncio()
async def test_k8s_cold_spec_shape(settings: Settings, signing_key: Path) -> None:
    s = replace(
        settings,
        runtime_backend="kubernetes",
        kube_namespace="sandbox",
        creds_signing_key_path=str(signing_key),
    )
    factory = _k8s_cold_spec_factory(s)
    cred = SessionCredential(
        cred_id="c1", session_id="s1", tenant_id="t1", expires_at=0, token="t.t"
    )
    spec = await factory("python-3.11-ctr", cred)
    assert spec["apiVersion"] == "v1"
    assert spec["kind"] == "Pod"
    assert spec["metadata"]["namespace"] == "sandbox"
    assert spec["metadata"]["labels"]["app"] == "sandbox"
    container = spec["spec"]["containers"][0]
    assert container["image"] == "python:3.11-slim"
    assert container["command"][0] == "sh"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert spec["spec"]["automountServiceAccountToken"] is False
    assert spec["spec"]["restartPolicy"] == "Never"


def test_k8s_pod_name_is_rfc1123_compliant() -> None:
    # Session ids come from secrets.token_hex and are prefixed `s_<hex>`;
    # K8s rejects `_` in metadata.name (RFC 1123 subdomain).
    name = _k8s_pod_name("s_6a3f430949f1301fa5392c3b")
    assert "_" not in name
    assert name == "sandbox-s-6a3f430949f1301fa5392c3b"


@pytest.mark.asyncio()
async def test_k8s_cold_spec_pod_name_rejects_underscores(
    settings: Settings, signing_key: Path
) -> None:
    s = replace(
        settings,
        runtime_backend="kubernetes",
        kube_namespace="sandbox",
        creds_signing_key_path=str(signing_key),
    )
    factory = _k8s_cold_spec_factory(s)
    cred = SessionCredential(
        cred_id="c1",
        session_id="s_6a3f430949f1301fa5392c3b",
        tenant_id="t1",
        expires_at=0,
        token="t.t",
    )
    spec = await factory("python-3.11-ctr", cred)
    assert "_" not in spec["metadata"]["name"]
    # sandbox_id label still carries the raw id — only the name is sanitized.
    assert spec["metadata"]["labels"]["sandbox_id"] == "s_6a3f430949f1301fa5392c3b"


def test_unknown_backend_raises(settings: Settings, signing_key: Path) -> None:
    s = replace(
        settings,
        runtime_backend="firecracker",  # not docker, not kubernetes
        creds_signing_key_path=str(signing_key),
    )
    with pytest.raises(BootError, match="unsupported RUNTIME_BACKEND"):
        build_context(s)


def test_build_app_mounts_sessions_route(
    settings: Settings, signing_key: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _docker_settings(settings, signing_key)
    monkeypatch.setattr(boot, "get_settings", lambda: s)
    app = build_app()
    paths = {getattr(route, "path", None) for route in app.router.routes}
    assert "/sessions/run" in paths
    assert "/healthz" in paths


@pytest.mark.asyncio()
async def test_docker_cold_spec_shape(settings: Settings, signing_key: Path) -> None:
    s = _docker_settings(settings, signing_key)
    factory = _docker_cold_spec_factory(s)
    cred = SessionCredential(
        cred_id="c1", session_id="s1", tenant_id="t1", expires_at=0, token="t.t"
    )
    spec = await factory("python-3.11-ctr", cred)
    assert spec["metadata"]["name"] == "sandbox-s1"
    assert spec["metadata"]["labels"]["sandbox_id"] == "s1"
    container = spec["spec"]["containers"][0]
    assert container["image"] == "python:3.11-slim"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True


def test_build_app_degrades_to_health_only_for_unknown_backend(
    settings: Settings, signing_key: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = replace(
        settings,
        runtime_backend="firecracker",
        creds_signing_key_path=str(signing_key),
    )
    monkeypatch.setattr(boot, "get_settings", lambda: s)
    app = build_app()
    paths = {getattr(route, "path", None) for route in app.router.routes}
    assert "/healthz" in paths
    assert "/sessions/run" not in paths


@pytest.mark.asyncio()
async def test_docker_cold_spec_unknown_flavor_raises(
    settings: Settings, signing_key: Path
) -> None:
    s = _docker_settings(settings, signing_key)
    factory = _docker_cold_spec_factory(s)
    cred = SessionCredential(
        cred_id="c1", session_id="s1", tenant_id="t1", expires_at=0, token="t.t"
    )
    with pytest.raises(BootError, match="no image mapping"):
        await factory("does-not-exist", cred)
