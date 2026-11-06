from __future__ import annotations

import pytest

from sandbox_ctl.config import ConfigError, load_settings, reset_settings_cache


def test_defaults_populate_when_env_sets_required(env_defaults: dict[str, str]) -> None:
    s = load_settings()
    assert s.service_name == "sandbox-ctl"
    assert s.http_port == 8080
    assert s.warm_pool_size == 16
    assert s.egress_default_policy == "deny"
    assert s.is_prod() is False


def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "RUNTIME_API_URL",
        "AGENT_GRPC_ENDPOINT",
        "SNAPSHOT_STORE_URL",
        "SNAPSHOT_STORE_BUCKET",
        "SNAPSHOT_STORE_KEY_ID",
        "SNAPSHOT_STORE_SECRET",
        "CREDS_SIGNING_KEY_PATH",
        "SANDBOX_IMAGE_PULL_SECRET",
    ]:
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    with pytest.raises(ConfigError, match="RUNTIME_API_URL"):
        load_settings()


def test_bool_parse_rejects_garbage(
    env_defaults: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KUBE_IN_CLUSTER", "maybe")
    with pytest.raises(ConfigError, match="KUBE_IN_CLUSTER"):
        load_settings()


def test_bad_env_name(env_defaults: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_ENV", "qa")
    with pytest.raises(ConfigError, match="SERVICE_ENV"):
        load_settings()


def test_sample_ratio_bounds(env_defaults: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTLP_SAMPLE_RATIO", "1.5")
    with pytest.raises(ConfigError, match="OTLP_SAMPLE_RATIO"):
        load_settings()


def test_runtime_backend_rejects_unknown(
    env_defaults: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_BACKEND", "podman")
    with pytest.raises(ConfigError, match="RUNTIME_BACKEND"):
        load_settings()


def test_runtime_backend_accepts_docker(
    env_defaults: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_BACKEND", "docker")
    s = load_settings()
    assert s.runtime_backend == "docker"
