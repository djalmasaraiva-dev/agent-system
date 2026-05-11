"""OpenTelemetry → Cloud Trace bootstrap, per Agent Starter Pack defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.utils.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = get_logger(__name__)


def setup_tracing(app: FastAPI, *, service_name: str, project_id: str, enabled: bool) -> None:
    """Wire OpenTelemetry into the FastAPI app and export traces to Cloud Trace.

    Best-effort — the system stays usable when OTel/Cloud Trace deps are missing
    or when ADC credentials are not yet configured.
    """
    if not enabled:
        logger.info("tracing.disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("tracing.deps_missing", error=str(exc))
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    try:
        provider.add_span_processor(
            BatchSpanProcessor(
                CloudTraceSpanExporter(project_id=project_id)  # type: ignore[no-untyped-call]
            )
        )
    except Exception as exc:
        logger.warning("tracing.exporter_init_failed", error=str(exc))
        return

    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    logger.info("tracing.enabled", service=service_name, project=project_id)
