"""Shared test fixtures.

The core concern: every test must get a Settings object without touching the
real environment or filesystem. ``settings_factory`` builds one with safe
defaults and lets individual tests override fields.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from sandbox_ctl.config import Settings, reset_settings_cache

_REQUIRED_ENV: dict[str, str] = {
    "RUNTIME_API_URL": "http://runtime.local",
    "AGENT_GRPC_ENDPOINT": "grpc://agent.local:50051",
    "SNAPSHOT_STORE_URL": "http://snap.local",
    "SNAPSHOT_STORE_BUCKET": "snaps",
    "SNAPSHOT_STORE_KEY_ID": "k",
    "SNAPSHOT_STORE_SECRET": "s",
    "CREDS_SIGNING_KEY_PATH": "",  # overridden per-test by `signing_key` fixture
    "SANDBOX_IMAGE_PULL_SECRET": "pull-secret",
    "OTLP_ENDPOINT": "",
    "SERVICE_ENV": "dev",
    "LOG_LEVEL": "WARNING",
    "LOG_FORMAT": "text",
    "KUBE_IN_CLUSTER": "false",
}


@pytest.fixture()
def signing_key(tmp_path: Path) -> Path:
    key = tmp_path / "signing.key"
    key.write_bytes(b"a" * 64)
    return key


@pytest.fixture()
def env_defaults(monkeypatch: pytest.MonkeyPatch, signing_key: Path) -> dict[str, str]:
    for k, v in _REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CREDS_SIGNING_KEY_PATH", str(signing_key))
    reset_settings_cache()
    return dict(os.environ)


@pytest.fixture()
def settings(env_defaults: dict[str, str]) -> Iterator[Settings]:
    from sandbox_ctl.config import load_settings

    yield load_settings()
    reset_settings_cache()
