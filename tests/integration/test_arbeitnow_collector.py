from contextlib import asynccontextmanager
from typing import AsyncGenerator
from datetime import datetime

from aiohttp import ClientSession
import pytest

from collection_service.arbeitnow_collector import ArbeitnowCollector
from models.collection_service import JobPosting


def ts(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


@asynccontextmanager
async def get_arbeitnow_collector() -> AsyncGenerator[ArbeitnowCollector, None]:
    client_session = ClientSession()
    try:
        collector = ArbeitnowCollector(client=client_session)
        yield collector
    finally:
        await client_session.close()


async def test_collect_returns_valid_result():
    async with get_arbeitnow_collector() as collector:
        result = await collector.collect(max_pages=1)
        assert result
        assert isinstance(result[0], JobPosting)
        assert result[0].source == "arbeitnow"
        assert result[0].uid.startswith("arbeitnow:")


async def test_collect_stops_when_posting_older_than_min_date():
    async with get_arbeitnow_collector() as collector:
        result = await collector.collect(min_date=ts("3000-01-01T00:00:00Z"))
        assert result == []


async def test_collect_raises_without_max_pages_or_min_date():
    async with get_arbeitnow_collector() as collector:
        with pytest.raises(ValueError, match="Either max_pages or min_date"):
            await collector.collect()


async def test_max_pages_limits_pages_fetched():
    async with get_arbeitnow_collector() as collector:
        one_page = await collector.collect(max_pages=1)
        two_pages = await collector.collect(max_pages=2)
        assert len(two_pages) > len(one_page)
