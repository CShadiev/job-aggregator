"""Correlation ID middleware for tracking HTTP request lifecycles."""

from __future__ import annotations

from uuid import uuid4

from opentelemetry import trace
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from telemetry import request_id_ctx


class CorrelationIdMiddleware:
    """ASGI middleware that ensures every HTTP request has an X-Request-ID correlation header.

    If an incoming X-Request-ID header is present, it is preserved; otherwise, a new UUID4 is generated.
    The request ID is stored in request_id_ctx for logger enrichment and attached to the outgoing response headers.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header_name = header_name
        self._header_name_bytes = header_name.lower().encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Look for existing incoming header
        req_id: str | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == self._header_name_bytes:
                req_id = value.decode("latin-1")
                break

        if not req_id:
            req_id = str(uuid4())

        token = request_id_ctx.set(req_id)

        # Tag active span with request ID if present
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("http.request_id", req_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((self._header_name_bytes, req_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)
