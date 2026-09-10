"""Convert string timestamp fields on jobs and nested assessment jobs back to datetime.

Some documents were written with ``posted_at``, ``collected_at``, and/or
``updated_at`` as ISO strings (e.g. via ``model_dump(mode="json")``) instead
of BSON datetimes.  This script finds those documents, parses the strings,
normalises them to UTC, and writes the corrections with ``bulk_write``.

Jobs are repaired at the top level.  Assessments are repaired on the
denormalized ``job`` snapshot (``job.posted_at``, etc.).
"""

from datetime import datetime
from typing import Any

from pymongo import UpdateOne
from pymongo.asynchronous.collection import AsyncCollection

from config import ConfigProvider
from logger_provider import LoggerProvider
from models.validators import ts_validator
from repository.mongo_jobs_repository import AsyncMongoClient

log = LoggerProvider.get_logger()

_TIMESTAMP_FIELDS = ("posted_at", "collected_at", "updated_at")


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a UTC-aware datetime."""
    return ts_validator(datetime.fromisoformat(value))


def _dotted_fields(prefix: str | None) -> tuple[str, ...]:
    """Return timestamp field paths, optionally nested under *prefix*."""
    if prefix is None:
        return _TIMESTAMP_FIELDS
    return tuple(f"{prefix}.{field}" for field in _TIMESTAMP_FIELDS)


def _read_field(doc: dict[str, Any], dotted: str) -> Any:
    """Read a possibly dotted field from a projected MongoDB document."""
    current: Any = doc
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


async def _fix_string_timestamps(
    collection: AsyncCollection,
    *,
    prefix: str | None,
    label: str,
) -> None:
    """Convert ISO string timestamps to UTC datetimes in *collection*.

    Args:
        collection: Target MongoDB collection.
        prefix: Optional nested document prefix (e.g. ``"job"``).
        label: Human-readable collection name used in log messages.
    """
    fields = _dotted_fields(prefix)
    query = {"$or": [{field: {"$type": "string"}} for field in fields]}
    projection = {field: 1 for field in fields}
    projection["_id"] = 1

    updates: list[UpdateOne] = []
    skipped = 0
    docs = await collection.find(query, projection=projection).to_list(None)
    log.info(
        "Found {n:d} {label} documents with string timestamps to update",
        n=len(docs),
        label=label,
    )
    for doc in docs:
        set_fields: dict[str, datetime] = {}
        for field in fields:
            value = _read_field(doc, field)
            if not isinstance(value, str):
                continue
            try:
                set_fields[field] = _parse_timestamp(value)
            except ValueError:
                skipped += 1
                log.warning(
                    "Skipping unparseable {field} on {label} {doc_id}: {value!r}",
                    field=field,
                    label=label,
                    doc_id=doc["_id"],
                    value=value,
                )

        if set_fields:
            updates.append(UpdateOne({"_id": doc["_id"]}, {"$set": set_fields}))

    log.info(
        "Prepared {n:d} {label} updates ({n_skipped:d} field(s) skipped)",
        n=len(updates),
        label=label,
        n_skipped=skipped,
    )
    if not updates:
        return

    result = await collection.bulk_write(updates, ordered=False)
    log.info(
        "{label} bulk_write complete: matched={matched:d} modified={modified:d}",
        label=label,
        matched=result.matched_count,
        modified=result.modified_count,
    )


async def fix_job_timestamp_types() -> None:
    """Find ISO string timestamps on jobs and nested assessment jobs and convert them to UTC datetimes."""
    config = ConfigProvider.get_config()
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    db = mongo_client.get_database(config.MONGODB_DATABASE)
    jobs = db.get_collection(config.MONGODB_JOBS_COLLECTION)
    assessments = db.get_collection(config.MONGODB_ASSESSMENTS_COLLECTION)

    await _fix_string_timestamps(jobs, prefix=None, label="jobs")
    await _fix_string_timestamps(assessments, prefix="job", label="assessments")


if __name__ == "__main__":
    import asyncio

    asyncio.run(fix_job_timestamp_types())
