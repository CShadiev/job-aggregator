"""Prometheus request metrics middleware for the FastAPI application."""

from __future__ import annotations

from time import perf_counter

from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from monitoring.metrics import record_http_request

_UNMATCHED_PATH = "unmatched"


class PrometheusMiddleware:
    """ASGI middleware recording request counts and latency per route template.

    The ``path`` label uses the matched route template (``/jobs/{job_uid}/status``)
    rather than the raw URL, so path parameters cannot blow up label cardinality.
    Requests that match no route are collapsed into a single ``unmatched`` series.
    """

    def __init__(self, app: ASGIApp, exclude_paths: tuple[str, ...] = ("/metrics",)) -> None:
        """Wrap *app*, skipping instrumentation for *exclude_paths* such as the scrape endpoint."""
        self.app = app
        self.exclude_paths = exclude_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        status_code = 500
        start = perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            record_http_request(
                method=scope.get("method", "GET"),
                path=_route_template(scope),
                status_code=status_code,
                duration_seconds=perf_counter() - start,
            )


def _route_template(scope: Scope) -> str:
    """Return the matched route template, or a placeholder when routing found nothing.

    Starlette writes the matched route into the scope during routing, so this is only
    meaningful once the inner application has run.
    """
    route = scope.get("route")
    if isinstance(route, Route):
        return route.path
    return _UNMATCHED_PATH
