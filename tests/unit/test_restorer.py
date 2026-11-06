from __future__ import annotations

from typing import Any

import httpx

from sandbox_ctl.runtime.driver import SandboxHandle
from sandbox_ctl.snapshot.restorer import Restorer
from sandbox_ctl.snapshot.store import SnapshotStore


class FakeDriver:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        self.created.append(pod_spec)
        return SandboxHandle(
            sandbox_id="s1",
            pod_name="sandbox-s1",
            namespace="ns",
            flavor_id=flavor_id,
            agent_endpoint="grpc://x",
        )

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None: ...
    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        return handle


async def test_restore_fetches_and_creates() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "snapshot_id": "snap_1",
                "base_image": "img",
                "kernel_version": "k",
                "memory_mb": 256,
                "tenant_id": "t",
                "size_bytes": 100,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SnapshotStore("http://snap.local", "snaps", client=client)

        async def factory(image: str, memory_mb: int) -> dict[str, Any]:
            return {
                "metadata": {"name": "sandbox-s1", "labels": {"sandbox_id": "s1"}},
                "spec": {"image": image, "memory_mb": memory_mb},
            }

        driver = FakeDriver()
        restorer = Restorer(store, driver, factory)
        handle, meta = await restorer.restore("snap_1")

    assert handle.sandbox_id == "s1"
    assert meta.base_image == "img"
    assert (
        driver.created[0]["metadata"]["annotations"]["sandbox-ctl.anthropic/restore-from"]
        == "snap_1"
    )
