from datetime import datetime, timezone

from pymongo import AsyncMongoClient

from models.job_application import JobApplicationStatus
from repository.mongo_jobs_repository import MongoJobsRepository
from config import ConfigProvider
from models.collection_service import JobPosting
from models.deduplication import NormalizedBatch, NormalizedJobEntry
from tests.datasets.job_feed_items import generate_job_feed_items


def make_job_posting(**overrides) -> JobPosting:
    defaults = {
        "uid": "test:1",
        "source": "test",
        "title": "Software Engineer",
        "company": "Acme Corp",
        "location": "",
        "remote": False,
        "url": "https://example.com/jobs/1",
        "description_raw": "Job description",
        "posted_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "collected_at": datetime(2026, 1, 1, tzinfo=timezone.utc), }
    defaults.update(overrides)
    return JobPosting(**defaults)


def make_normalized_batch(entries: list[tuple[str, str, str]]) -> NormalizedBatch:
    return NormalizedBatch(
        jobs=[NormalizedJobEntry(id=id_, title=title, company=company) for id_, title, company in entries])


async def setup_test_db(username: str):
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST, port=config.MONGODB_PORT, username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD)

    try:
        repo = MongoJobsRepository(mongo_client, database=config.MONGODB_TEST_DATABASE)
        await repo._assessments.delete_many({})
        await repo._jobs.delete_many({})
        await repo._applications.delete_many({})
        job_items = generate_job_feed_items(username)
        await repo.store_processed_jobs([item.job for item in job_items])
        assessments = [(item.fit, username, item.job.uid) for item in job_items]
        await repo.store_many_assessments(assessments)
        statuses = [
            JobApplicationStatus(
                username=username, job_uid=item.job.uid, stage=item.status.stage, skipped=item.status.skipped)
            for item in job_items if item.status is not None]
        await repo.insert_many_job_application_statuses(statuses)

    finally:
        await mongo_client.close()
