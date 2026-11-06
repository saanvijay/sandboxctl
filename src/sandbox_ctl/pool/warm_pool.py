"""Warm-pool bookkeeping.

Holds idle sandbox handles per flavor. Lease takes one off the queue if
available; return (``release``) puts a fresh sandbox back. Entries older
than ``WARM_POOL_MAX_IDLE_S`` are evicted lazily on lookup.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from sandbox_ctl.runtime.driver import SandboxHandle

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Entry:
    handle: SandboxHandle
    created_at: float


class WarmPool:
    """In-memory warm pool.

    Thread-safe via an asyncio Lock — assumed to be used from a single event
    loop, which is the control-plane model.
    """

    def __init__(self, max_idle_s: int) -> None:
        if max_idle_s <= 0:
            raise ValueError("max_idle_s must be > 0")
        self._max_idle_s = max_idle_s
        self._lock = asyncio.Lock()
        self._q: dict[str, deque[_Entry]] = defaultdict(deque)

    async def size(self, flavor_id: str) -> int:
        async with self._lock:
            self._prune(flavor_id)
            return len(self._q[flavor_id])

    async def sizes(self) -> dict[str, int]:
        async with self._lock:
            return {flavor: len(q) for flavor, q in self._q.items()}

    async def lease(self, flavor_id: str) -> SandboxHandle | None:
        async with self._lock:
            self._prune(flavor_id)
            q = self._q[flavor_id]
            if not q:
                return None
            entry = q.popleft()
            return entry.handle

    async def release(self, handle: SandboxHandle) -> None:
        async with self._lock:
            self._q[handle.flavor_id].append(_Entry(handle=handle, created_at=time.monotonic()))

    async def drain(self) -> list[SandboxHandle]:
        async with self._lock:
            drained: list[SandboxHandle] = []
            for q in self._q.values():
                while q:
                    drained.append(q.popleft().handle)
            return drained

    async def expired(self) -> list[SandboxHandle]:
        async with self._lock:
            expired: list[SandboxHandle] = []
            cutoff = time.monotonic() - self._max_idle_s
            for q in self._q.values():
                remaining: deque[_Entry] = deque()
                while q:
                    e = q.popleft()
                    if e.created_at < cutoff:
                        expired.append(e.handle)
                    else:
                        remaining.append(e)
                q.extend(remaining)
            return expired

    def _prune(self, flavor_id: str) -> None:
        cutoff = time.monotonic() - self._max_idle_s
        q = self._q[flavor_id]
        while q and q[0].created_at < cutoff:
            dropped = q.popleft()
            logger.info(
                "pruned stale warm sandbox",
                extra={"flavor_id": flavor_id, "sandbox_id": dropped.handle.sandbox_id},
            )
