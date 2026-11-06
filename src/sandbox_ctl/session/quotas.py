"""Per-tenant and per-session quota enforcement.

Two kinds of quotas:

- Concurrency: a hard cap on in-flight sessions per tenant.
- Rate: a token bucket on session *creations* per second per tenant.

Both are in-memory and single-replica. A production deployment adds a
shared cache in front of this (e.g. Redis) when more than one control-plane
replica serves a tenant.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class QuotaError(RuntimeError):
    """Raised when a tenant exceeds their quota."""


@dataclass(frozen=True, slots=True)
class QuotaConfig:
    max_concurrent: int
    rps: int

    def __post_init__(self) -> None:
        if self.max_concurrent <= 0:
            raise ValueError("max_concurrent must be > 0")
        if self.rps <= 0:
            raise ValueError("rps must be > 0")


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, tokens: float) -> None:
        self.tokens = tokens
        self.last_refill = time.monotonic()


class QuotaEnforcer:
    """Concurrency semaphore + token-bucket rate limiter per tenant."""

    def __init__(self, config: QuotaConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._inflight: dict[str, int] = defaultdict(int)
        self._buckets: dict[str, _Bucket] = {}

    async def acquire(self, tenant_id: str) -> None:
        """Reserve a session slot. Raises :class:`QuotaError` on breach."""
        async with self._lock:
            if self._inflight[tenant_id] >= self._config.max_concurrent:
                raise QuotaError(
                    f"tenant {tenant_id} exceeded concurrent cap "
                    f"({self._config.max_concurrent})"
                )
            bucket = self._bucket(tenant_id)
            self._refill(bucket)
            if bucket.tokens < 1.0:
                raise QuotaError(f"tenant {tenant_id} exceeded rate ({self._config.rps} rps)")
            bucket.tokens -= 1.0
            self._inflight[tenant_id] += 1

    async def release(self, tenant_id: str) -> None:
        async with self._lock:
            if self._inflight[tenant_id] > 0:
                self._inflight[tenant_id] -= 1

    def inflight(self, tenant_id: str) -> int:
        return self._inflight.get(tenant_id, 0)

    def _bucket(self, tenant_id: str) -> _Bucket:
        bucket = self._buckets.get(tenant_id)
        if bucket is None:
            bucket = _Bucket(tokens=float(self._config.rps))
            self._buckets[tenant_id] = bucket
        return bucket

    def _refill(self, bucket: _Bucket) -> None:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(float(self._config.rps), bucket.tokens + elapsed * self._config.rps)
        bucket.last_refill = now
