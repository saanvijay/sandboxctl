from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sandbox_ctl.runtime.driver import SandboxHandle

pytestmark = pytest.mark.e2e


async def test_warm_hit_bypasses_cold_create(stack: dict[str, object]) -> None:
    pool = stack["pool"]
    driver = stack["driver"]
    client: TestClient = stack["client"]  # type: ignore[assignment]

    for i in range(3):
        await pool.release(  # type: ignore[attr-defined]
            SandboxHandle(
                sandbox_id=f"warm_{i}",
                pod_name=f"sandbox-warm_{i}",
                namespace="sandbox",
                flavor_id="python-3.11-ctr",
                agent_endpoint="grpc://warm:50051",
            )
        )

    for _ in range(3):
        r = client.post(
            "/sessions/run",
            headers={"X-Tenant-Id": "demo"},
            json={"code": "x", "language": "python", "timeout_s": 5},
        )
        assert r.status_code == 200

    assert len(driver.created) == 0  # type: ignore[attr-defined]
    assert len(driver.relabels) == 3  # type: ignore[attr-defined]


async def test_warm_miss_falls_back_to_cold(stack: dict[str, object]) -> None:
    client: TestClient = stack["client"]  # type: ignore[assignment]
    driver = stack["driver"]
    r = client.post(
        "/sessions/run",
        headers={"X-Tenant-Id": "demo"},
        json={"code": "x", "language": "python", "timeout_s": 5},
    )
    assert r.status_code == 200
    assert len(driver.created) == 1  # type: ignore[attr-defined]
