from __future__ import annotations

import asyncio

import pytest

from sandbox_ctl.session.quotas import QuotaConfig, QuotaEnforcer, QuotaError


async def test_concurrency_cap() -> None:
    q = QuotaEnforcer(QuotaConfig(max_concurrent=2, rps=100))
    await q.acquire("t")
    await q.acquire("t")
    with pytest.raises(QuotaError, match="concurrent"):
        await q.acquire("t")
    await q.release("t")
    await q.acquire("t")


async def test_rate_limit() -> None:
    q = QuotaEnforcer(QuotaConfig(max_concurrent=1000, rps=2))
    await q.acquire("t")
    await q.acquire("t")
    with pytest.raises(QuotaError, match="rate"):
        await q.acquire("t")
    await asyncio.sleep(1.1)
    await q.acquire("t")


async def test_isolation_between_tenants() -> None:
    q = QuotaEnforcer(QuotaConfig(max_concurrent=1, rps=1000))
    await q.acquire("a")
    await q.acquire("b")  # must not be blocked by a's slot
