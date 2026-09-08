"""Prometheus exposition endpoint scraped by the Grafana Alloy collector."""

from fastapi import APIRouter, Response

from monitoring.metrics import render_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """
    Prometheus scrape endpoint exposing the default collector registry.
    """
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)
