from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sandbox_ctl.session.state import SessionPhase

pytestmark = pytest.mark.e2e


def test_credentials_minted_and_revoked_each_session(
    stack: dict[str, object], signing_key: Path
) -> None:
    client: TestClient = stack["client"]  # type: ignore[assignment]
    events = stack["events"]
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "demo"},
        json={"code": "x", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    sid = r.json()["session_id"]

    kinds = [e.kind for e in events.events_for(sid)]  # type: ignore[attr-defined]
    assert "isolated" in kinds
    assert "destroyed" in kinds
    # Final phase is DESTROYED, which is where creds are revoked.
    r2 = client.get(f"/sessions/{sid}", headers={"X-Tenant-Id": "demo"})
    assert r2.json()["phase"] == SessionPhase.DESTROYED.value


def test_credentials_not_logged_in_response(stack: dict[str, object]) -> None:
    client: TestClient = stack["client"]  # type: ignore[assignment]
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "demo"},
        json={"code": "x", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    body_text = r.text
    assert "SESSION_CREDENTIAL" not in body_text
    assert "cred_id" not in body_text
    assert "signing" not in body_text
