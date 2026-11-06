from __future__ import annotations

from prometheus_client import CollectorRegistry

from sandbox_ctl.telemetry.metrics import build_metrics


def test_build_metrics_registers_all() -> None:
    r = CollectorRegistry()
    m = build_metrics(r)
    m.sessions_created_total.labels(tenant="t1").inc()
    m.pool_occupancy.labels(flavor="python-3.11-ctr").set(5)
    m.cold_start_seconds.labels(flavor="python-3.11-ctr").observe(0.1)

    families = list(r.collect())
    names = {f.name for f in families}
    # prometheus_client strips the `_total` suffix from the family name.
    assert "sandbox_sessions_created" in names
    assert "sandbox_pool_occupancy" in names
    assert "sandbox_cold_start_seconds" in names
