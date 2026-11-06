"""Prometheus metrics registration.

One module, one registry wiring. Metric *names* and label *sets* are stable;
if you add a new metric, add a one-line docstring and a unit suffix.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

_LATENCY_BUCKETS_S = (0.01, 0.03, 0.05, 0.1, 0.3, 0.5, 1.0, 3.0, 10.0, 30.0)


@dataclass(frozen=True, slots=True)
class Metrics:
    cold_start_seconds: Histogram
    warm_start_seconds: Histogram
    snapshot_restore_seconds: Histogram
    session_wall_seconds: Histogram
    teardown_seconds: Histogram
    pool_occupancy: Gauge
    pool_miss_total: Counter
    pool_hit_total: Counter
    egress_denies_total: Counter
    teardown_failures_total: Counter
    sessions_inflight: Gauge
    sessions_created_total: Counter


def build_metrics(registry: CollectorRegistry | None = None) -> Metrics:
    """Create and register all metrics against ``registry``.

    Passing a fresh registry is the test-friendly path — avoids collisions with
    the default global registry across runs.
    """
    r = registry or CollectorRegistry()
    return Metrics(
        cold_start_seconds=Histogram(
            "sandbox_cold_start_seconds",
            "Time from lease decision to sandbox-ready, cold path.",
            labelnames=("flavor",),
            buckets=_LATENCY_BUCKETS_S,
            registry=r,
        ),
        warm_start_seconds=Histogram(
            "sandbox_warm_start_seconds",
            "Time from lease decision to sandbox-ready, warm path.",
            labelnames=("flavor",),
            buckets=_LATENCY_BUCKETS_S,
            registry=r,
        ),
        snapshot_restore_seconds=Histogram(
            "sandbox_snapshot_restore_seconds",
            "Time to restore a session from a snapshot.",
            labelnames=("flavor",),
            buckets=_LATENCY_BUCKETS_S,
            registry=r,
        ),
        session_wall_seconds=Histogram(
            "sandbox_session_wall_seconds",
            "End-to-end wall time per session.",
            labelnames=("flavor", "outcome"),
            buckets=_LATENCY_BUCKETS_S,
            registry=r,
        ),
        teardown_seconds=Histogram(
            "sandbox_teardown_seconds",
            "Time to destroy a sandbox.",
            labelnames=("flavor",),
            buckets=_LATENCY_BUCKETS_S,
            registry=r,
        ),
        pool_occupancy=Gauge(
            "sandbox_pool_occupancy",
            "Current count of warm sandboxes available per flavor.",
            labelnames=("flavor",),
            registry=r,
        ),
        pool_miss_total=Counter(
            "sandbox_pool_miss_total",
            "Lease requests that found an empty pool.",
            labelnames=("flavor",),
            registry=r,
        ),
        pool_hit_total=Counter(
            "sandbox_pool_hit_total",
            "Lease requests served from the pool.",
            labelnames=("flavor",),
            registry=r,
        ),
        egress_denies_total=Counter(
            "sandbox_egress_denies_total",
            "Egress attempts denied by the per-session allowlist.",
            labelnames=("tenant",),
            registry=r,
        ),
        teardown_failures_total=Counter(
            "sandbox_teardown_failures_total",
            "Sessions where destroy returned a non-success.",
            labelnames=("reason",),
            registry=r,
        ),
        sessions_inflight=Gauge(
            "sandbox_sessions_inflight",
            "Sessions currently executing on this control-plane replica.",
            registry=r,
        ),
        sessions_created_total=Counter(
            "sandbox_sessions_created_total",
            "Total sessions created, by tenant.",
            labelnames=("tenant",),
            registry=r,
        ),
    )


def start_metrics_server(port: int, registry: CollectorRegistry) -> None:
    """Expose metrics on ``/metrics`` at ``port``."""
    logger.info("starting metrics server", extra={"metrics_port": port})
    start_http_server(port, registry=registry)
