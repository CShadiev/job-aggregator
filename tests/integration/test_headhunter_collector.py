"""Live test for HeadHunterCollector against public hh.ru pages.

CI does not collect this file. Run it locally with
``uv run pytest tests/integration/test_headhunter_collector.py``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from aiohttp import ClientSession

from collection_service.headhunter_collector import HeadHunterCollector
from models.collection_service import JobPosting


@asynccontextmanager
async def get_headhunter_collector() -> AsyncGenerator[HeadHunterCollector]:
    """Provide a HeadHunterCollector bound to a session this test closes."""
    client_session = ClientSession()
    try:
        yield HeadHunterCollector(client=client_session)
    finally:
        await client_session.close()


async def test_collect_jobs_stops_newer_than_one_day():
    """Fetch real vacancies and stop once postings are older than one day ago."""
    min_date = datetime.now(UTC) - timedelta(days=1)
    async with get_headhunter_collector() as collector:
        result = await collector.collect_jobs(min_date=min_date)

    assert result.postings
    print(f"total number: {len(result.postings)}")
    for posting in result.postings:
        print(f"posting: {posting}")
        assert isinstance(posting, JobPosting)
        assert posting.posted_at > min_date
        assert posting.source == "headhunter"
        assert posting.uid.startswith("headhunter:")
        assert posting.title
        assert posting.company
        assert posting.description_raw
