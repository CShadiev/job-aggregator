from contextlib import asynccontextmanager
from typing import AsyncGenerator
from datetime import datetime

from aiohttp import ClientSession
import pytest

from collection_service.apify_collector import ApifyCollector
from collection_service.apify_parser_protocol import IApifyParser
from collection_service.exceptions import MissingEntriesError
from collection_service.indeed_apify_parser import IndeedApifyParser
from models.collection_service import JobPosting, InvalidEntry


def ts(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


class FaultyApifyParser:

    def parse_job(self, raw: dict) -> JobPosting:
        return JobPosting.model_validate(raw)


@asynccontextmanager
async def get_apify_collector(run_apify_task: bool = False,
                              parser: IApifyParser | None = None) -> AsyncGenerator[ApifyCollector, None]:
    client_session = ClientSession()
    try:
        apify_collector = ApifyCollector(
            client_session=client_session,
            task_id="hopeful_quarter~indeed-scraper-task",
            source_tag="indeed",
            apify_parser=parser or IndeedApifyParser("indeed"),
            run_apify_task=run_apify_task,
        )
        yield apify_collector
    finally:
        await client_session.close()


@pytest.mark.priced
async def test_collect_with_run_returns_valid_result():
    async with get_apify_collector(run_apify_task=True) as apify_collector:
        result = await apify_collector.collect()
        assert result.postings
        assert isinstance(result.postings[0], JobPosting)


async def test_collect_returns_valid_result():
    async with get_apify_collector() as apify_collector:
        result = await apify_collector.collect()
        assert result.postings
        assert isinstance(result.postings[0], JobPosting)


async def test_raises_missing_entries_error_if_min_date_lower_than_earliest_entry():
    async with get_apify_collector() as apify_collector:
        with pytest.raises(MissingEntriesError):
            await apify_collector.collect(min_date=ts("2026-01-01T00:00:00Z"))


async def test_returns_invalid_entries():
    async with get_apify_collector(parser=FaultyApifyParser()) as apify_collector:
        result = await apify_collector.collect()
        assert result.invalid_entries
        assert isinstance(result.invalid_entries[0], InvalidEntry)
