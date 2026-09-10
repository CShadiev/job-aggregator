"""Integration tests for MongoJobsRepository against a live MongoDB test instance."""

from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from pymongo import AsyncMongoClient

from config import ConfigProvider
from models.fit_assessment import FitAssessment
from models.generics import PaginatedDataRequest
from models.jobs_api import JobFeedQuery
from repository.mongo_jobs_repository import MongoJobsRepository
from tests.datasets.job_feed_items import generate_job_feed_items
from tests.helpers.job_posting import make_job_posting

_USERNAME = "test_user"


@pytest.fixture()
async def repo() -> AsyncGenerator[MongoJobsRepository]:
    """Provide a seeded MongoJobsRepository connected to the test database."""
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    db = mongo_client[config.MONGODB_TEST_DATABASE]
    jobs_count = await db[config.MONGODB_JOBS_COLLECTION].count_documents({})
    if jobs_count == 0:
        items = generate_job_feed_items(_USERNAME)
        await db[config.MONGODB_JOBS_COLLECTION].insert_many(
            [item.job.model_dump() for item in items]
        )
        await db[config.MONGODB_ASSESSMENTS_COLLECTION].insert_many(
            [
                {
                    "username": _USERNAME,
                    "job_uid": item.job.uid,
                    "assessment": item.fit.model_dump(mode="json"),
                }
                for item in items
                if item.fit is not None
            ]
        )
        statuses = [item.status.model_dump() for item in items if item.status is not None]
        if statuses:
            await db[config.MONGODB_JOB_APPLICATIONS_COLLECTION].insert_many(statuses)

    repo = MongoJobsRepository(mongo_client, database=config.MONGODB_TEST_DATABASE)
    yield repo
    await mongo_client.close()


class TestGetJobFeedPagination:
    """Tests for job feed item pagination and filtering in MongoJobsRepository."""

    async def test_nonlast_page_returns_correct_number_of_items(self, repo: MongoJobsRepository):
        """Verify pagination returns requested page size."""
        request = PaginatedDataRequest[JobFeedQuery](
            query=JobFeedQuery(skipped=False), page=1, page_size=100
        )
        response = await repo.get_job_feed_items(request, _USERNAME)
        assert response.total > 100
        assert len(response.data) == 100

    async def test_skipped_jobs_are_excluded(self, repo: MongoJobsRepository):
        """Verify skipped jobs are excluded when skipped=False filter is applied."""
        request = PaginatedDataRequest[JobFeedQuery](
            query=JobFeedQuery(skipped=False, active_only=False), page=1, page_size=1000
        )
        response = await repo.get_job_feed_items(request, _USERNAME)
        assert response.total > 0
        skipped_jobs = [
            item for item in response.data if item.status is not None and item.status.skipped
        ]
        assert len(skipped_jobs) == 0


class TestStoreAssessmentTimestampTypes:
    """Verify Mongo writes persist JobPosting timestamps as BSON datetimes."""

    async def test_nested_job_timestamps_are_datetimes(self, repo: MongoJobsRepository):
        """store_assessment must write nested job.posted_at as datetime, not ISO string."""
        username = "datetime_type_user"
        job = make_job_posting(uid="datetime-type:1")
        assessment = FitAssessment(
            cv_ats_match_score=80,
            profile_ats_match_score=75,
            summary="nested timestamp type check",
        )
        await repo.store_assessment(assessment, username, job.uid, job=job)
        try:
            doc = await repo._assessments.find_one({"username": username, "job_uid": job.uid})
            assert doc is not None
            nested = doc["job"]
            assert isinstance(nested["posted_at"], datetime)
            assert isinstance(nested["collected_at"], datetime)
            assert isinstance(nested["updated_at"], datetime)
        finally:
            await repo._assessments.delete_many({"username": username, "job_uid": job.uid})
            await repo._applications.delete_many({"username": username, "job_uid": job.uid})
