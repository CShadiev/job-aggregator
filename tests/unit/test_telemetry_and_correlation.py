"""Unit tests for OpenTelemetry tracing, span IDs, and request correlation middleware."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from logger_provider import LoggerProvider
from main import app
from telemetry import (
    cycle_id_ctx,
    get_current_span_id,
    get_current_trace_id,
    get_tracer,
    request_id_ctx,
)


@pytest.fixture
def client():
    """Create a FastAPI TestClient instance."""
    return TestClient(app, raise_server_exceptions=False)


def test_correlation_middleware_generates_request_id(client: TestClient):
    """Verify that requests without X-Request-ID receive a newly generated UUID."""
    response = client.get("/healthz")
    assert response.status_code == 200
    req_id = response.headers.get("X-Request-ID")
    assert req_id is not None
    # Validate that it is a valid UUID
    uuid_obj = UUID(req_id)
    assert str(uuid_obj) == req_id


def test_correlation_middleware_preserves_request_id(client: TestClient):
    """Verify that incoming X-Request-ID headers are preserved and propagated in response."""
    custom_id = "test-correlation-id-12345"
    response = client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id


def test_telemetry_trace_and_span_ids():
    """Verify extraction of active OpenTelemetry trace and span IDs."""
    # Outside of an active span
    assert get_current_trace_id() is None
    assert get_current_span_id() is None

    # Inside an active span
    tracer = get_tracer("test.tracer")
    with tracer.start_as_current_span("test-operation"):
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()

        assert trace_id is not None
        assert len(trace_id) == 32
        assert span_id is not None
        assert len(span_id) == 16


def test_loguru_record_enrichment():
    """Verify that loguru log records are enriched with trace, span, and request context."""
    logger = LoggerProvider.get_logger()
    captured_records = []

    def sink(message):
        captured_records.append(message.record)

    sink_id = logger.add(sink)
    try:
        req_token = request_id_ctx.set("req-test-abc")
        cycle_token = cycle_id_ctx.set("cycle-test-xyz")
        tracer = get_tracer("test.logger")

        with tracer.start_as_current_span("logged-span"):
            logger.info("Test log message with full context")

        request_id_ctx.reset(req_token)
        cycle_id_ctx.reset(cycle_token)

        assert len(captured_records) == 1
        extra = captured_records[0]["extra"]
        assert extra.get("request_id") == "req-test-abc"
        assert extra.get("cycle_id") == "cycle-test-xyz"
        assert "trace_id" in extra
        assert "span_id" in extra
        assert len(extra["trace_id"]) == 32
        assert len(extra["span_id"]) == 16
    finally:
        logger.remove(sink_id)
