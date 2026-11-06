from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sandbox_ctl.runtime.driver import SandboxHandle
from sandbox_ctl.snapshot.checkpointer import Checkpointer, CheckpointRequest
from sandbox_ctl.snapshot.restorer import Restorer
from sandbox_ctl.snapshot.store import SnapshotStore
from tests.unit.fakes import FakeDriver

pytestmark = pytest.mark.e2e


async def test_checkpoint_then_restore_round_trip() -> None:
    stored: dict[str, dict[str, object]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        snap_id = request.url.path.split("/")[-2]
        if request.method == "PUT":
            stored[snap_id] = json.loads(request.content.decode())
            return httpx.Response(200, json={})
        if request.method == "GET":
            return httpx.Response(200, json=stored[snap_id])
        return httpx.Response(405)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SnapshotStore("http://snap.local", "snaps", client=client)

        async def upload(_: SandboxHandle, __: str) -> int:
            return 2048

        source = SandboxHandle(
            sandbox_id="orig",
            pod_name="sandbox-orig",
            namespace="sandbox",
            flavor_id="python-3.11-ctr",
            agent_endpoint="grpc://orig",
        )
        checkpointer = Checkpointer(store, upload)
        meta = await checkpointer.checkpoint(
            source,
            CheckpointRequest(
                tenant_id="demo", base_image="python:3.11", kernel_version="6.1", memory_mb=256
            ),
        )

        driver = FakeDriver()

        async def spec_factory(image: str, memory_mb: int) -> dict[str, Any]:
            return {
                "metadata": {"name": "sandbox-restored", "labels": {"sandbox_id": "restored"}},
                "spec": {"image": image, "memory_mb": memory_mb},
            }

        restorer = Restorer(store, driver, spec_factory)
        handle, restored_meta = await restorer.restore(meta.snapshot_id)

    assert restored_meta.snapshot_id == meta.snapshot_id
    assert handle.sandbox_id == "sbx_1"  # from FakeDriver
    assert (
        driver.created[0]["metadata"]["annotations"]["sandbox-ctl.anthropic/restore-from"]
        == meta.snapshot_id
    )
