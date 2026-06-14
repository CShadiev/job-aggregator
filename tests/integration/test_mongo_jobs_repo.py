from typing import AsyncGenerator
from pymongo import AsyncMongoClient
from models.generics import PaginatedDataRequest
from models.jobs_api import JobFeedQuery
from repository.mongo_jobs_repository import MongoJobsRepository
from config import ConfigProvider
import pytest

from tests.helpers.job_posting import setup_test_db

_USERNAME = "test_user"


@pytest.fixture()
async def repo() -> AsyncGenerator[MongoJobsRepository, None]:
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST, port=config.MONGODB_PORT, username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD)
    repo = MongoJobsRepository(mongo_client, database=config.MONGODB_TEST_DATABASE)
    yield repo
    await mongo_client.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    await setup_test_db(_USERNAME)


class TestGetJobFeedPagination:

    async def test_nonlast_page_returns_correct_number_of_items(self, repo: MongoJobsRepository):
        request = PaginatedDataRequest[JobFeedQuery](query=JobFeedQuery(skipped=False), page=1, page_size=100)
        response = await repo.get_job_feed_items(request, _USERNAME)
        assert response.total > 100
        assert len(response.data) == 100
        MAX_PAGES = response.total // 100 + 1
        for page in range(2, MAX_PAGES):
            request = PaginatedDataRequest[JobFeedQuery](query=JobFeedQuery(skipped=False), page=page, page_size=100)
            response = await repo.get_job_feed_items(request, _USERNAME)
            assert response.total == response.total
            assert len(response.data) == 100
