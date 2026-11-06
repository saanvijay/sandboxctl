"""E2E fixtures.

These tests exercise the full happy-path through the SessionManager and API
using in-process fakes for the runtime driver and in-sandbox agent. The same
tests can be pointed at a real cluster by swapping the fakes for the real
``K8sDriver`` and gRPC agent client; see ``make test-e2e`` in a cluster env.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sandbox_ctl.api.app import AppContext, create_app
from sandbox_ctl.api.auth import DevHeaderAuth
from sandbox_ctl.config import Settings
from sandbox_ctl.isolation.creds import CredentialMinter, SessionCredential
from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.agent_client import RunResult
from sandbox_ctl.session.manager import SessionManager
from sandbox_ctl.session.quotas import QuotaConfig, QuotaEnforcer
from sandbox_ctl.session.registry import SessionRegistry
from sandbox_ctl.telemetry.events import EventEmitter
from tests.unit.fakes import FakeAgent, FakeDriver


async def _cold_spec(flavor: str, cred: SessionCredential) -> dict[str, object]:
    return {
        "metadata": {
            "name": f"sandbox-{cred.session_id}",
            "labels": {"sandbox_id": cred.session_id, "flavor_id": flavor},
        }
    }


@pytest.fixture()
def stack(settings: Settings, signing_key: Path) -> Iterator[dict[str, object]]:
    driver = FakeDriver()
    agent = FakeAgent(RunResult(exit_code=0, stdout="ok\n", stderr="", duration_ms=1))
    registry = SessionRegistry()
    pool = WarmPool(max_idle_s=60)
    events = EventEmitter()
    manager = SessionManager(
        settings=settings,
        driver=driver,
        pool=pool,
        agent=agent,
        creds=CredentialMinter(str(signing_key), ttl_s=60),
        quotas=QuotaEnforcer(QuotaConfig(max_concurrent=4, rps=100)),
        registry=registry,
        events=events,
        cold_spec_factory=_cold_spec,
    )
    client = TestClient(
        create_app(
            AppContext(settings=settings, manager=manager, registry=registry, auth=DevHeaderAuth())
        )
    )
    yield {
        "driver": driver,
        "agent": agent,
        "registry": registry,
        "pool": pool,
        "events": events,
        "manager": manager,
        "client": client,
    }
