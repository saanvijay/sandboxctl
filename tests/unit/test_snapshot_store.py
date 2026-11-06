from __future__ import annotations

import json

import httpx
import pytest

from sandbox_ctl.snapshot.store import SnapshotMeta, SnapshotStore, SnapshotStoreError


def _meta() -> SnapshotMeta:
    return SnapshotMeta(
        snapshot_id="snap_1",
        base_image="python:3.11",
        kernel_version="5.15",
        memory_mb=256,
        tenant_id="t",
        size_bytes=4096,
    )


async def test_put_and_get_round_trip() -> None:
    stored: dict[str, dict[str, object]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        snap_id = request.url.path.split("/")[-2]
        if request.method == "PUT":
            stored[snap_id] = json.loads(request.content.decode())
            return httpx.Response(200, json={})
        if request.method == "GET":
            return httpx.Response(200, json=stored[snap_id])
        return httpx.Response(405)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        store = SnapshotStore("http://snap.local", "snaps", client=client)
        meta = _meta()
        await store.put(meta)
        fetched = await store.get("snap_1")
        assert fetched == meta


async def test_list_for_tenant_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snapshot_id": "snap_a",
                        "base_image": "img",
                        "kernel_version": "k",
                        "memory_mb": 128,
                        "tenant_id": "t",
                        "size_bytes": 10,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SnapshotStore("http://snap.local", "snaps", client=client)
        rows = await store.list_for_tenant("t")
        assert len(rows) == 1
        assert rows[0].snapshot_id == "snap_a"


async def test_server_error_wrapped() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SnapshotStore("http://snap.local", "snaps", client=client)
        with pytest.raises(SnapshotStoreError):
            await store.get("snap_1")
