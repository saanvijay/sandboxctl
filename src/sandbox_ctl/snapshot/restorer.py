"""Restore a sandbox from a snapshot id."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sandbox_ctl.runtime.driver import Driver, SandboxHandle
from sandbox_ctl.snapshot.store import SnapshotMeta, SnapshotStore

logger = logging.getLogger(__name__)


# Spec factory: (base image, memory_mb) -> Pod spec dict.
SpecFactory = Callable[[str, int], Awaitable[dict[str, Any]]]


class Restorer:
    """Fetch a snapshot's metadata and bring a sandbox back up from it.

    Credentials and egress state do **not** survive restore and must be
    re-minted by the caller (see DESIGN.md §5.2 and §8).
    """

    def __init__(self, store: SnapshotStore, driver: Driver, spec_factory: SpecFactory) -> None:
        self._store = store
        self._driver = driver
        self._factory = spec_factory

    async def restore(self, snapshot_id: str) -> tuple[SandboxHandle, SnapshotMeta]:
        meta = await self._store.get(snapshot_id)
        spec = await self._factory(meta.base_image, meta.memory_mb)
        spec.setdefault("metadata", {}).setdefault("annotations", {})[
            "sandbox-ctl.anthropic/restore-from"
        ] = snapshot_id
        handle = await self._driver.create(spec, flavor_id=meta.base_image)
        logger.info(
            "restore complete",
            extra={"snapshot_id": snapshot_id, "sandbox_id": handle.sandbox_id},
        )
        return handle, meta
