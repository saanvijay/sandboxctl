from __future__ import annotations

from sandbox_ctl.config import Settings
from sandbox_ctl.telemetry.tracer import configure_tracing, get_tracer


def test_configure_tracing_without_otlp(settings: Settings) -> None:
    provider = configure_tracing(settings)
    assert provider is not None
    tracer = get_tracer("x")
    with tracer.start_as_current_span("probe") as span:
        assert span is not None
