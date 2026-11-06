from __future__ import annotations

import pytest

from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.driver import SandboxHandle


def _handle(sid: str, flavor: str = "python-3.11-ctr") -> SandboxHandle:
    return SandboxHandle(
        sandbox_id=sid,
        pod_name=f"sandbox-{sid}",
        namespace="sandbox",
        flavor_id=flavor,
        agent_endpoint="grpc://x:50051",
    )


async def test_lease_from_empty_pool_returns_none() -> None:
    pool = WarmPool(max_idle_s=60)
    assert await pool.lease("f") is None


async def test_release_then_lease() -> None:
    pool = WarmPool(max_idle_s=60)
    await pool.release(_handle("a"))
    await pool.release(_handle("b"))
    first = await pool.lease("python-3.11-ctr")
    second = await pool.lease("python-3.11-ctr")
    assert first is not None and first.sandbox_id == "a"
    assert second is not None and second.sandbox_id == "b"


async def test_pool_isolation_per_flavor() -> None:
    pool = WarmPool(max_idle_s=60)
    await pool.release(_handle("py-1", flavor="python"))
    assert await pool.lease("node") is None
    assert (await pool.lease("python")) is not None


async def test_sizes() -> None:
    pool = WarmPool(max_idle_s=60)
    await pool.release(_handle("a"))
    sizes = await pool.sizes()
    assert sizes["python-3.11-ctr"] == 1


async def test_invalid_max_idle() -> None:
    with pytest.raises(ValueError):
        WarmPool(max_idle_s=0)


async def test_drain() -> None:
    pool = WarmPool(max_idle_s=60)
    await pool.release(_handle("a"))
    await pool.release(_handle("b", flavor="other"))
    drained = await pool.drain()
    ids = {h.sandbox_id for h in drained}
    assert ids == {"a", "b"}
