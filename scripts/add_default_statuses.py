"""Migration script to backfill default JobApplicationStatus documents for existing assessments."""

from pymongo import InsertOne

from config import ConfigProvider
from logger_provider import LoggerProvider
from models.job_application import JobApplicationStatus
from repository.mongo_jobs_repository import AsyncMongoClient

log = LoggerProvider.get_logger()


async def add_default_statuses() -> None:
    """Scan existing assessments collection and insert missing default JobApplicationStatus records."""
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    mdb = mongo_client.get_database(config.MONGODB_DATABASE)

    assessments = mdb.get_collection(config.MONGODB_ASSESSMENTS_COLLECTION)
    applications = mdb.get_collection(config.MONGODB_JOB_APPLICATIONS_COLLECTION)

    existing_keys = {
        (doc["username"], doc["job_uid"])
        async for doc in applications.find({}, projection={"username": 1, "job_uid": 1, "_id": 0})
    }

    inserts: list[InsertOne] = []
    seen: set[tuple[str, str]] = set()
    async for doc in assessments.find({}, projection={"username": 1, "job_uid": 1, "_id": 0}):
        key = (doc["username"], doc["job_uid"])
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        status = JobApplicationStatus(username=doc["username"], job_uid=doc["job_uid"])
        inserts.append(InsertOne(status.model_dump()))

    log.info(f"Found {len(inserts)} assessments without a job application status")
    if not inserts:
        return

    log.info(f"Inserting {len(inserts)} default job application statuses")
    result = await applications.bulk_write(inserts)
    log.info(f"Inserted {result.inserted_count} default job application statuses")


if __name__ == "__main__":
    import asyncio

    asyncio.run(add_default_statuses())
