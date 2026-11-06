"""Warm-pool refill loop.

Keeps ``WARM_POOL_SIZE`` sandboxes available per flavor by creating new ones
via the runtime driver whenever the pool is low. Refills in bounded parallel
batches of ``WARM_POOL_REFILL_CONCURRENCY``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.driver import Driver, DriverError, SandboxHandle

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefillConfig:
    size_per_flavor: int
    concurrency: int
    tick_s: float = 1.0


SpecFactory = Callable[[str], Awaitable[dict[str, object]]]
"""Given a flavor id, return the Pod spec dict for a fresh warm sandbox."""


class Refiller:
    """Background task that keeps the warm pool at target size."""

    def __init__(
        self,
        pool: WarmPool,
        driver: Driver,
        spec_factory: SpecFactory,
        flavors: tuple[str, ...],
        config: RefillConfig,
    ) -> None:
        if config.size_per_flavor < 0:
            raise ValueError("size_per_flavor must be >= 0")
        if config.concurrency <= 0:
            raise ValueError("concurrency must be > 0")
        self._pool = pool
        self._driver = driver
        self._factory = spec_factory
        self._flavors = flavors
        self._config = config
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="warm-pool-refiller")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.refill_once()
            except Exception:
                logger.exception("refill tick failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._config.tick_s)
            except TimeoutError:
                continue

    async def refill_once(self) -> None:
        for flavor in self._flavors:
            current = await self._pool.size(flavor)
            deficit = self._config.size_per_flavor - current
            if deficit <= 0:
                continue
            logger.info(
                "refilling warm pool",
                extra={"flavor_id": flavor, "current": current, "deficit": deficit},
            )
            await self._create_many(flavor, deficit)

    async def _create_many(self, flavor: str, n: int) -> None:
        sem = asyncio.Semaphore(self._config.concurrency)

        async def one() -> None:
            async with sem:
                try:
                    handle = await self._create_one(flavor)
                except DriverError:
                    logger.exception("warm sandbox create failed", extra={"flavor_id": flavor})
                    return
                await self._pool.release(handle)

        await asyncio.gather(*(one() for _ in range(n)))

    async def _create_one(self, flavor: str) -> SandboxHandle:
        spec = await self._factory(flavor)
        return await self._driver.create(spec, flavor_id=flavor)
