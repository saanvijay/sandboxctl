from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sandbox_ctl.session.state import SessionPhase

pytestmark = pytest.mark.e2e


def test_create_exec_destroy(stack: dict[str, object]) -> None:
    client: TestClient = stack["client"]  # type: ignore[assignment]
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "demo"},
        json={"code": "print(1)", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    sid = r.json()["session_id"]
    r2 = client.get(f"/sessions/{sid}", headers={"X-Tenant-Id": "demo"})
    assert r2.status_code == 200
    assert r2.json()["phase"] == SessionPhase.DESTROYED.value


def test_sandbox_is_destroyed(stack: dict[str, object]) -> None:
    client: TestClient = stack["client"]  # type: ignore[assignment]
    driver = stack["driver"]
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "demo"},
        json={"code": "x", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    # Every created sandbox is also destroyed.
    assert len(driver.destroyed) == 1  # type: ignore[attr-defined]
    assert len(driver.destroyed) == len(driver.created)  # type: ignore[attr-defined]
