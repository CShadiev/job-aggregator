from collections.abc import AsyncGenerator

import pytest
from pymongo import AsyncMongoClient

from config import ConfigProvider
from models.generics import PaginatedDataRequest
from models.jobs_api import JobFeedQuery
from repository.mongo_jobs_repository import MongoJobsRepository

_USERNAME = "test_user"


@pytest.fixture()
async def repo() -> AsyncGenerator[MongoJobsRepository]:
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    repo = MongoJobsRepository(mongo_client, database=config.MONGODB_TEST_DATABASE)
    yield repo
    await mongo_client.close()


class TestGetJobFeedPagination:
    async def test_nonlast_page_returns_correct_number_of_items(self, repo: MongoJobsRepository):
        request = PaginatedDataRequest[JobFeedQuery](
            query=JobFeedQuery(skipped=False), page=1, page_size=100
        )
        response = await repo.get_job_feed_items(request, _USERNAME)
        assert response.total > 100
        assert len(response.data) == 100

    async def test_skipped_jobs_are_excluded(self, repo: MongoJobsRepository):
        request = PaginatedDataRequest[JobFeedQuery](
            query=JobFeedQuery(skipped=False, active_only=False), page=1, page_size=1000
        )
        response = await repo.get_job_feed_items(request, _USERNAME)
        assert response.total > 0
        skipped_jobs = [
            item for item in response.data if item.status is not None and item.status.skipped
        ]
        assert len(skipped_jobs) == 0
