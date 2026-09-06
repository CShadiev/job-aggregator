"""Integration tests for ApifyCollector scraping Indeed and LinkedIn data."""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Protocol

import pytest
from aiohttp import ClientSession

from collection_service.apify_collector import ApifyCollector
from collection_service.apify_parser_protocol import IApifyParser
from collection_service.exceptions import MissingEntriesError
from collection_service.indeed_apify_parser import IndeedApifyParser
from collection_service.linkedin_apify_parser import LinkedinApifyParser
from config import ConfigProvider
from models.collection_service import InvalidEntry, JobPosting

cfg = ConfigProvider.get_config()


def ts(timestamp: str) -> datetime:
    """Parse an ISO format datetime string."""
    return datetime.fromisoformat(timestamp)


class FaultyApifyParser:
    """Parser mock that deliberately fails validation for error handling tests."""

    def parse_job(self, raw: dict) -> JobPosting:
        """Attempt parsing with an empty dictionary to trigger validation error."""
        return JobPosting.model_validate({})


class ApifyCollectorFactory(Protocol):
    """Protocol signature for the test Apify collector async factory fixture."""

    def __call__(
        self, run_apify_task: bool = False, parser: IApifyParser | None = None
    ) -> AbstractAsyncContextManager[ApifyCollector]: ...


test_params = [
    ("indeed", cfg.APIFY_INDEED_TASK_ID, IndeedApifyParser("indeed")),
    ("linkedin", cfg.APIFY_LINKEDIN_TASK_ID, LinkedinApifyParser("linkedin")),
]


@pytest.fixture(params=test_params)
def get_apify_collector(request) -> ApifyCollectorFactory:
    """Fixture providing an ApifyCollectorFactory for parameterized scrapers."""
    source_tag, task_id, default_parser = request.param

    @asynccontextmanager
    async def factory(
        run_apify_task: bool = False, parser: IApifyParser | None = None
    ) -> AsyncGenerator[ApifyCollector]:
        client_session = ClientSession()
        try:
            apify_collector = ApifyCollector(
                client_session=client_session,
                task_id=task_id,
                source_tag=source_tag,
                apify_parser=parser or default_parser,
                run_apify_task=run_apify_task,
            )
            yield apify_collector
        finally:
            await client_session.close()

    return factory


@pytest.mark.priced
async def test_collect_with_run_returns_valid_result(get_apify_collector: ApifyCollectorFactory):
    """Test running the live Apify scraping actor task and collecting results."""
    async with get_apify_collector(run_apify_task=True) as apify_collector:
        result = await apify_collector.collect_jobs()
        print(result.invalid_entries[0])
        assert result.postings
        assert isinstance(result.postings[0], JobPosting)


async def test_collect_returns_valid_result(get_apify_collector: ApifyCollectorFactory):
    """Test fetching pre-existing Apify dataset items without running a new scrape task."""
    async with get_apify_collector() as apify_collector:
        result = await apify_collector.collect_jobs()
        assert result.postings
        assert isinstance(result.postings[0], JobPosting)


async def test_raises_missing_entries_error_if_min_date_lower_than_earliest_entry(
    get_apify_collector: ApifyCollectorFactory,
):
    """Test error raised when oldest collected dataset item is newer than min_date."""
    async with get_apify_collector() as apify_collector:
        with pytest.raises(MissingEntriesError):
            await apify_collector.collect_jobs(min_date=ts("2000-01-01T00:00:00Z"))


async def test_returns_invalid_entries(get_apify_collector: ApifyCollectorFactory):
    """Test collector records unparseable items into invalid_entries list."""
    async with get_apify_collector(parser=FaultyApifyParser()) as apify_collector:
        result = await apify_collector.collect_jobs()
        assert result.invalid_entries
        assert isinstance(result.invalid_entries[0], InvalidEntry)
