"""Backfill nested job/status on Mongo assessments and index OpenSearch."""

from __future__ import annotations

import argparse
import asyncio

from pymongo import AsyncMongoClient, UpdateOne

from config import ConfigProvider
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.job_application import JobApplicationStatus
from search.client import build_opensearch_client
from search.models import DenormalizedAssessment
from search.search_service import SearchService

log = LoggerProvider.get_logger()


async def migrate(*, batch_size: int) -> None:
    config = ConfigProvider.get_config()
    mongo = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    db = mongo[config.MONGODB_DATABASE]
    assessments = db[config.MONGODB_ASSESSMENTS_COLLECTION]
    jobs = db[config.MONGODB_JOBS_COLLECTION]
    applications = db[config.MONGODB_JOB_APPLICATIONS_COLLECTION]
    search = SearchService(build_opensearch_client(config), config=config)
    try:
        await search.ensure_indices()
        cursor = assessments.find()
        mongo_ops: list[UpdateOne] = []
        os_docs: list[DenormalizedAssessment] = []
        migrated = 0
        skipped = 0
        async for doc in cursor:
            username = doc.get("username")
            job_uid = doc.get("job_uid")
            raw_assessment = doc.get("assessment")
            if not username or not job_uid or not raw_assessment:
                skipped += 1
                continue
            job_doc = doc.get("job") or await jobs.find_one({"uid": job_uid})
            if job_doc is None:
                skipped += 1
                continue
            app_doc = doc.get("status") or await applications.find_one(
                {"username": username, "job_uid": job_uid}
            )
            job = JobPosting.model_validate(job_doc)
            status = (
                JobApplicationStatus.model_validate(app_doc)
                if app_doc
                else JobApplicationStatus(username=username, job_uid=job_uid)
            )
            assessment = FitAssessment.model_validate(raw_assessment)
            denorm = DenormalizedAssessment.from_parts(
                assessment=assessment, username=username, job=job, status=status
            )
            mongo_ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "job": job.model_dump(mode="json"),
                            "status": status.model_dump(mode="json"),
                        }
                    },
                )
            )
            os_docs.append(denorm)
            if len(mongo_ops) >= batch_size:
                await assessments.bulk_write(mongo_ops, ordered=False)
                await search.bulk_index_assessments(os_docs)
                migrated += len(os_docs)
                mongo_ops = []
                os_docs = []
        if mongo_ops:
            await assessments.bulk_write(mongo_ops, ordered=False)
            await search.bulk_index_assessments(os_docs)
            migrated += len(os_docs)
        log.info("Migrated {n} assessments, skipped {skipped}", n=migrated, skipped=skipped)
    finally:
        await search.close()
        await mongo.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(migrate(batch_size=args.batch_size))


if __name__ == "__main__":
    main()
