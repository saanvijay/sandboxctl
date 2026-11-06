"""OpenTelemetry tracer provider setup.

Wires an OTLP gRPC exporter when ``OTLP_ENDPOINT`` is set; otherwise installs
a no-op provider so instrumentation code can call it unconditionally.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from sandbox_ctl.config import Settings

logger = logging.getLogger(__name__)


def configure_tracing(settings: Settings) -> trace.TracerProvider:
    """Configure the global tracer provider and return it."""
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.environment": settings.service_env,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(settings.otlp_sample_ratio),
    )
    if settings.otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(
                "tracing enabled",
                extra={"otlp_endpoint": settings.otlp_endpoint},
            )
        except Exception:
            logger.exception("failed to install OTLP exporter — continuing without export")
    else:
        logger.info("tracing: no OTLP endpoint configured, spans dropped")
    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
