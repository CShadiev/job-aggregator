"""OpenTelemetry initialization and trace correlation helpers."""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from config import ConfigProvider

if TYPE_CHECKING:
    from fastapi import FastAPI

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
cycle_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("cycle_id", default=None)

_is_instrumented: bool = False


def setup_telemetry(service_name: str | None = None) -> TracerProvider:
    """Initialize the OpenTelemetry TracerProvider and auto-instrument core libraries."""
    global _is_instrumented

    config = ConfigProvider.get_config()
    name = service_name or config.OTEL_SERVICE_NAME

    resource = Resource.create(
        {
            "service.name": name,
            "service.version": "0.1.0",
        }
    )

    provider = TracerProvider(resource=resource)

    # Configure trace exporters based on environment / configuration
    if config.OTEL_TRACES_EXPORTER == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif config.OTEL_EXPORTER_OTLP_ENDPOINT:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # pyright: ignore[reportMissingImports]
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=config.OTEL_EXPORTER_OTLP_ENDPOINT))
            )
        except ImportError:
            pass

    trace.set_tracer_provider(provider)

    if not _is_instrumented:
        PymongoInstrumentor().instrument(tracer_provider=provider)
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        AioHttpClientInstrumentor().instrument(tracer_provider=provider)
        _is_instrumented = True

    return provider


def instrument_fastapi(app: FastAPI) -> None:
    """Instrument the FastAPI application with OpenTelemetry tracing."""
    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str = "job-aggregator") -> trace.Tracer:
    """Return an OpenTelemetry Tracer instance."""
    return trace.get_tracer(name)


def get_current_trace_id() -> str | None:
    """Return the active span's 32-hex trace ID, or None if no valid span is active."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        if ctx.is_valid:
            return f"{ctx.trace_id:032x}"
    return None


def get_current_span_id() -> str | None:
    """Return the active span's 16-hex span ID, or None if no valid span is active."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        if ctx.is_valid:
            return f"{ctx.span_id:016x}"
    return None
