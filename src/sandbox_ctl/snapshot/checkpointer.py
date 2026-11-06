"""Checkpoint a running sandbox into a snapshot in the store."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sandbox_ctl.runtime.driver import SandboxHandle
from sandbox_ctl.snapshot.store import SnapshotMeta, SnapshotStore

logger = logging.getLogger(__name__)


# Signature: (handle, snapshot_id) -> uploaded size in bytes.
UploadFn = Callable[[SandboxHandle, str], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class CheckpointRequest:
    tenant_id: str
    base_image: str
    kernel_version: str
    memory_mb: int


class Checkpointer:
    """Drive a checkpoint through the runtime and record it in the store.

    The runtime side (pausing the sandbox, writing the snapshot payload to
    object storage) is external — we hold a callable that performs it so this
    module stays free of transport details.
    """

    def __init__(self, store: SnapshotStore, upload_payload: UploadFn) -> None:
        self._store = store
        self._upload = upload_payload

    async def checkpoint(self, handle: SandboxHandle, request: CheckpointRequest) -> SnapshotMeta:
        snapshot_id = f"snap_{secrets.token_hex(12)}"
        size_bytes = await self._upload(handle, snapshot_id)
        meta = SnapshotMeta(
            snapshot_id=snapshot_id,
            base_image=request.base_image,
            kernel_version=request.kernel_version,
            memory_mb=request.memory_mb,
            tenant_id=request.tenant_id,
            size_bytes=size_bytes,
        )
        await self._store.put(meta)
        logger.info(
            "checkpoint complete",
            extra={"snapshot_id": snapshot_id, "sandbox_id": handle.sandbox_id},
        )
        return meta
