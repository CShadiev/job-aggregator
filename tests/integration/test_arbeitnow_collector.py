"""Integration tests for ArbeitnowCollector job scraping API client."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from aiohttp import ClientSession

from collection_service.arbeitnow_collector import ArbeitnowCollector
from models.collection_service import JobPosting


def ts(timestamp: str) -> datetime:
    """Parse an ISO format datetime string."""
    return datetime.fromisoformat(timestamp)


@asynccontextmanager
async def get_arbeitnow_collector() -> AsyncGenerator[ArbeitnowCollector]:
    """Async context manager fixture providing an ArbeitnowCollector with an open ClientSession."""
    client_session = ClientSession()
    try:
        collector = ArbeitnowCollector(client=client_session)
        yield collector
    finally:
        await client_session.close()


async def test_collect_returns_valid_result():
    """Verify collector fetches valid JobPosting objects from Arbeitnow API."""
    async with get_arbeitnow_collector() as collector:
        result = await collector.collect(max_pages=1)
        assert result
        assert isinstance(result[0], JobPosting)
        assert result[0].source == "arbeitnow"
        assert result[0].uid.startswith("arbeitnow:")


async def test_collect_stops_when_posting_older_than_min_date():
    """Verify collector stops pagination when jobs are older than min_date threshold."""
    async with get_arbeitnow_collector() as collector:
        result = await collector.collect(min_date=ts("3000-01-01T00:00:00Z"))
        assert result == []


async def test_collect_raises_without_max_pages_or_min_date():
    """Verify ValueError is raised if neither max_pages nor min_date is supplied."""
    async with get_arbeitnow_collector() as collector:
        with pytest.raises(ValueError, match="Either max_pages or min_date"):
            await collector.collect()


async def test_max_pages_limits_pages_fetched():
    """Verify max_pages parameter caps the number of pages retrieved."""
    async with get_arbeitnow_collector() as collector:
        one_page = await collector.collect(max_pages=1)
        two_pages = await collector.collect(max_pages=2)
        assert len(two_pages) > len(one_page)
