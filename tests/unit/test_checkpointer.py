from __future__ import annotations

import httpx

from sandbox_ctl.runtime.driver import SandboxHandle
from sandbox_ctl.snapshot.checkpointer import Checkpointer, CheckpointRequest
from sandbox_ctl.snapshot.store import SnapshotStore


async def test_checkpoint_writes_meta_to_store() -> None:
    captured: dict[str, dict[str, object]] = {}
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            captured[request.url.path] = json.loads(request.content.decode())
            return httpx.Response(200, json={})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SnapshotStore("http://snap.local", "snaps", client=client)

        async def upload(_handle: SandboxHandle, _snapshot_id: str) -> int:
            return 1024

        cp = Checkpointer(store, upload)
        handle = SandboxHandle(
            sandbox_id="s", pod_name="p", namespace="ns", flavor_id="f", agent_endpoint=""
        )
        meta = await cp.checkpoint(
            handle,
            CheckpointRequest(tenant_id="t", base_image="img", kernel_version="k", memory_mb=256),
        )

    assert meta.size_bytes == 1024
    assert meta.base_image == "img"
    assert any("meta" in path for path in captured)
