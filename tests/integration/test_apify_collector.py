from contextlib import asynccontextmanager
from typing import AsyncContextManager, AsyncGenerator, Protocol
from datetime import datetime

from aiohttp import ClientSession
import pytest

from collection_service.apify_collector import ApifyCollector
from collection_service.apify_parser_protocol import IApifyParser
from collection_service.exceptions import MissingEntriesError
from collection_service.indeed_apify_parser import IndeedApifyParser
from collection_service.linkedin_apify_parser import LinkedinApifyParser
from models.collection_service import JobPosting, InvalidEntry

from config import ConfigProvider

cfg = ConfigProvider.get_config()


def ts(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


class FaultyApifyParser:

    def parse_job(self, raw: dict) -> JobPosting:
        return JobPosting.model_validate({})


class ApifyCollectorFactory(Protocol):

    def __call__(self, run_apify_task: bool = False,
                 parser: IApifyParser | None = None) -> AsyncContextManager[ApifyCollector]:
        ...


test_params = [("indeed", cfg.APIFY_INDEED_TASK_ID, IndeedApifyParser("indeed")),
               ("linkedin", cfg.APIFY_LINKEDIN_TASK_ID, LinkedinApifyParser("linkedin"))]


@pytest.fixture(params=test_params)
def get_apify_collector(request) -> ApifyCollectorFactory:
    source_tag, task_id, default_parser = request.param

    @asynccontextmanager
    async def factory(run_apify_task: bool = False,
                      parser: IApifyParser | None = None) -> AsyncGenerator[ApifyCollector, None]:
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
    async with get_apify_collector(run_apify_task=True) as apify_collector:
        result = await apify_collector.collect_jobs()
        print(result.invalid_entries[0])
        assert result.postings
        assert isinstance(result.postings[0], JobPosting)


async def test_collect_returns_valid_result(get_apify_collector: ApifyCollectorFactory):
    async with get_apify_collector() as apify_collector:
        result = await apify_collector.collect_jobs()
        assert result.postings
        assert isinstance(result.postings[0], JobPosting)


async def test_raises_missing_entries_error_if_min_date_lower_than_earliest_entry(
        get_apify_collector: ApifyCollectorFactory):

    async with get_apify_collector() as apify_collector:
        with pytest.raises(MissingEntriesError):
            await apify_collector.collect_jobs(min_date=ts("2000-01-01T00:00:00Z"))


async def test_returns_invalid_entries(get_apify_collector: ApifyCollectorFactory):
    async with get_apify_collector(parser=FaultyApifyParser()) as apify_collector:
        result = await apify_collector.collect_jobs()
        assert result.invalid_entries
        assert isinstance(result.invalid_entries[0], InvalidEntry)
