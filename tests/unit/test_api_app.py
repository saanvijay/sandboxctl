from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sandbox_ctl.api.app import AppContext, create_app
from sandbox_ctl.api.auth import DevHeaderAuth
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
            "labels": {"sandbox_id": cred.session_id},
        }
    }


@pytest.fixture()
def client(settings: object, signing_key: Path) -> TestClient:
    driver = FakeDriver()
    agent = FakeAgent(RunResult(exit_code=0, stdout="ok\n", stderr="", duration_ms=1))
    registry = SessionRegistry()
    manager = SessionManager(
        settings=settings,  # type: ignore[arg-type]
        driver=driver,
        pool=WarmPool(max_idle_s=60),
        agent=agent,
        creds=CredentialMinter(str(signing_key), ttl_s=60),
        quotas=QuotaEnforcer(QuotaConfig(max_concurrent=4, rps=100)),
        registry=registry,
        events=EventEmitter(),
        cold_spec_factory=_cold_spec,
    )
    ctx = AppContext(
        settings=settings,  # type: ignore[arg-type]
        manager=manager,
        registry=registry,
        auth=DevHeaderAuth(),
    )
    return TestClient(create_app(ctx))


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_run_requires_tenant_header(client: TestClient) -> None:
    r = client.post("/sessions/run", json={"code": "x", "language": "python"})
    assert r.status_code == 401


def test_run_happy_path(client: TestClient) -> None:
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "t1"},
        json={"code": "print(1)", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0
    assert body["stdout"] == "ok\n"


def test_get_session_tenant_isolation(client: TestClient) -> None:
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "owner"},
        json={"code": "x", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    sid = r.json()["session_id"]
    # Different tenant can't see it.
    r2 = client.get(f"/sessions/{sid}", headers={"X-Tenant-Id": "other"})
    assert r2.status_code == 404
    # Owner can.
    r3 = client.get(f"/sessions/{sid}", headers={"X-Tenant-Id": "owner"})
    assert r3.status_code == 200
    assert r3.json()["session_id"] == sid
