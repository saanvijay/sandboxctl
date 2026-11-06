from __future__ import annotations

from typing import Any

import pytest

from sandbox_ctl.pool.refiller import RefillConfig, Refiller
from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.driver import DriverError, SandboxHandle


class CountingDriver:
    def __init__(self, fail_every: int = 0) -> None:
        self.count = 0
        self.fail_every = fail_every

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        self.count += 1
        if self.fail_every and self.count % self.fail_every == 0:
            raise DriverError("boom")
        return SandboxHandle(
            sandbox_id=f"id-{self.count}",
            pod_name=f"sandbox-{self.count}",
            namespace="sandbox",
            flavor_id=flavor_id,
            agent_endpoint="grpc://x",
        )

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None:
        return None

    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        return handle


async def _spec_factory(flavor: str) -> dict[str, object]:
    return {"metadata": {"name": f"sandbox-{flavor}", "labels": {"sandbox_id": "x"}}}


async def test_refill_once_fills_to_target() -> None:
    pool = WarmPool(max_idle_s=60)
    driver = CountingDriver()
    refiller = Refiller(
        pool=pool,
        driver=driver,
        spec_factory=_spec_factory,
        flavors=("python-3.11-ctr",),
        config=RefillConfig(size_per_flavor=3, concurrency=2),
    )
    await refiller.refill_once()
    assert await pool.size("python-3.11-ctr") == 3


async def test_refill_tolerates_driver_errors() -> None:
    pool = WarmPool(max_idle_s=60)
    driver = CountingDriver(fail_every=2)
    refiller = Refiller(
        pool=pool,
        driver=driver,
        spec_factory=_spec_factory,
        flavors=("f",),
        config=RefillConfig(size_per_flavor=4, concurrency=2),
    )
    await refiller.refill_once()
    size = await pool.size("f")
    assert size == 2


async def test_rejects_negative_target() -> None:
    with pytest.raises(ValueError):
        Refiller(
            pool=WarmPool(max_idle_s=60),
            driver=CountingDriver(),
            spec_factory=_spec_factory,
            flavors=("f",),
            config=RefillConfig(size_per_flavor=-1, concurrency=1),
        )
