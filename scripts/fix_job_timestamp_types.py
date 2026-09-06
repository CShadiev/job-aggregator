"""Convert string timestamp fields on jobs documents back to datetime.

Some jobs were written with ``posted_at``, ``collected_at``, and/or
``updated_at`` as ISO strings (e.g. via ``model_dump(mode="json")``) instead
of BSON datetimes.  This script finds those documents, parses the strings,
normalises them to UTC, and writes the corrections with ``bulk_write``.
"""

from datetime import datetime

from pymongo import UpdateOne

from config import ConfigProvider
from logger_provider import LoggerProvider
from models.validators import ts_validator
from repository.mongo_jobs_repository import AsyncMongoClient

log = LoggerProvider.get_logger()

_TIMESTAMP_FIELDS = ("posted_at", "collected_at", "updated_at")


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a UTC-aware datetime."""
    return ts_validator(datetime.fromisoformat(value))


async def fix_job_timestamp_types() -> None:
    """Find MongoDB jobs with ISO string timestamps and convert them to UTC datetime objects."""
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    jobs = mongo_client.get_database(config.MONGODB_DATABASE).get_collection(
        config.MONGODB_JOBS_COLLECTION
    )

    query = {
        "$or": [{field: {"$type": "string"}} for field in _TIMESTAMP_FIELDS],
    }
    projection = {field: 1 for field in _TIMESTAMP_FIELDS}
    projection["_id"] = 1

    updates: list[UpdateOne] = []
    skipped = 0
    docs = await jobs.find(query, projection=projection).to_list(None)
    log.info("Found {n_jobs:d} jobs with string timestamps to update", n_jobs=len(docs))
    for doc in docs:
        set_fields: dict[str, datetime] = {}
        for field in _TIMESTAMP_FIELDS:
            value = doc.get(field)
            if not isinstance(value, str):
                continue
            try:
                set_fields[field] = _parse_timestamp(value)
            except ValueError:
                skipped += 1
                log.warning("Skipping unparseable %s on job %s: %r", field, doc["_id"], value)

        if set_fields:
            updates.append(UpdateOne({"_id": doc["_id"]}, {"$set": set_fields}))

    log.info(
        "Found {n_jobs:d} jobs with string timestamps to update ({n_skipped:d} field(s) skipped)",
        n_jobs=len(updates),
        n_skipped=skipped,
    )
    if not updates:
        return

    result = await jobs.bulk_write(updates, ordered=False)
    log.info(
        "bulk_write complete: matched=%d modified=%d",
        result.matched_count,
        result.modified_count,
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(fix_job_timestamp_types())
