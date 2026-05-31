from datetime import datetime, timezone
from typing import Sequence, Union

from pymongo import AsyncMongoClient, UpdateOne

from config import ConfigProvider
from models.collection_service import InvalidEntry, JobPosting
from models.deduplication import FailedJobPosting
from models.fit_assessment import FitAssessment
from models.pipeline import PipelineStage
from models.users import UserProfile
from models.validators import ts_validator

config = ConfigProvider.get_config()

FailedEntry = Union[InvalidEntry, FailedJobPosting]


def _to_utc(value: datetime) -> datetime:
    return ts_validator(value)


def _job_posting_to_processing_doc(posting: JobPosting, stage: str) -> dict:
    return {**posting.model_dump(), "pipeline_stage": stage}


class MongoJobsRepository:
    """MongoDB-backed implementation of :class:`~repository.protocol.IRepository`.

    Expects job documents keyed by ``uid`` with fields aligned to
    :class:`~models.collection_service.JobPosting`.  Checkpoints are stored in a
    separate collection, keyed by ``source_id``.

    The processing collection holds in-flight job descriptions keyed by ``uid``
    and ``pipeline_stage``.  The failed collection stores entries that could not
    complete a pipeline step.
    """

    def __init__(
        self,
        client: AsyncMongoClient,
    ) -> None:
        db = client[config.MONGODB_DATABASE]
        self._jobs = db[config.MONGODB_JOBS_COLLECTION]
        self._checkpoints = db[config.MONGODB_CHECKPOINTS_COLLECTION]
        self._processing = db[config.MONGODB_PROCESSING_COLLECTION]
        self._failed = db[config.MONGODB_FAILED_COLLECTION]
        self._user_profiles = db[config.MONGODB_USER_PROFILES_COLLECTION]
        self._assessments = db[config.MONGODB_ASSESSMENTS_COLLECTION]

    async def get_checkpoint(self, source_id: str) -> datetime | None:
        doc = await self._checkpoints.find_one({"_id": source_id}, projection={"checkpoint": 1, "_id": 0})
        if doc is None:
            return None
        return _to_utc(doc["checkpoint"])

    async def set_checkpoint(self, source_id: str, checkpoint: datetime) -> None:
        await self._checkpoints.update_one(
            {"_id": source_id},
            {"$set": {"checkpoint": _to_utc(checkpoint)}},
            upsert=True,
        )

    async def store_assessment(self, assessment: FitAssessment, username: str, job_uid: str) -> None:
        await self._assessments.insert_one({
            "username": username,
            "job_uid": job_uid,
            "assessment": assessment.model_dump(mode="json"), })

    async def get_existing_uids(self, uids: set[str]) -> set[str]:
        if not uids:
            return set()
        cursor = self._jobs.find({"uid": {"$in": list(uids)}}, projection={"uid": 1, "_id": 0})
        return {doc["uid"] async for doc in cursor}

    async def get_recent_normalized_keys(
        self,
        keys: set[tuple[str, str]],
        since: datetime,
    ) -> set[tuple[str, str]]:
        if not keys:
            return set()
        since_utc = _to_utc(since)
        conditions = [{
            "title_normalized": title,
            "company_normalized": company,
            "posted_at": {"$gte": since_utc}, } for title, company in keys]
        cursor = self._jobs.find(
            {"$or": conditions},
            projection={"title_normalized": 1, "company_normalized": 1, "_id": 0},
        )
        return {(doc["title_normalized"], doc["company_normalized"])
                async for doc in cursor
                if doc.get("title_normalized") is not None and doc.get("company_normalized") is not None}

    async def store_in_processing(self, postings: list[JobPosting]) -> int:
        """Enqueue collected jobs for the normalization worker.

        Skips UIDs already present in the jobs or processing collections so a
        job is not queued twice.

        Returns:
            Number of postings inserted.
        """
        if not postings:
            return 0
        uids = {p.uid for p in postings}
        existing = await self.get_existing_uids(uids)
        cursor = self._processing.find({"uid": {"$in": list(uids)}}, projection={"uid": 1, "_id": 0})
        in_processing = {doc["uid"] async for doc in cursor}
        skip = existing | in_processing
        to_insert = [p for p in postings if p.uid not in skip]
        if not to_insert:
            return 0
        await self._processing.insert_many([
            _job_posting_to_processing_doc(p, PipelineStage.COLLECTED) for p in to_insert])
        return len(to_insert)

    async def get_normalization_feed(self, limit: int = 50) -> list[JobPosting]:
        """Return jobs awaiting title/company normalization."""
        cursor = self._processing.find(
            {"pipeline_stage": PipelineStage.COLLECTED},
            limit=limit,
        )
        return [JobPosting.model_validate(doc) async for doc in cursor]

    async def get_deduplication_feed(self, limit: int = 50) -> list[JobPosting]:
        """Return normalized jobs awaiting cross-source deduplication."""
        cursor = self._processing.find(
            {"pipeline_stage": PipelineStage.NORMALIZED},
            limit=limit,
        )
        return [JobPosting.model_validate(doc) async for doc in cursor]

    async def get_assessment_feed(self, limit: int = 50) -> list[JobPosting]:
        """Return deduplicated jobs awaiting fit assessment."""
        cursor = self._processing.find(
            {"pipeline_stage": PipelineStage.DEDUPLICATED},
            limit=limit,
        )
        return [JobPosting.model_validate(doc) async for doc in cursor]

    async def save_normalized_results(self, postings: list[JobPosting]) -> None:
        """Persist normalization output and advance jobs to the deduplication stage."""
        if not postings:
            return
        ops = [
            UpdateOne(
                {"uid": posting.uid, "pipeline_stage": PipelineStage.COLLECTED},
                {"$set": _job_posting_to_processing_doc(posting, PipelineStage.NORMALIZED)},
            ) for posting in postings]
        await self._processing.bulk_write(ops, ordered=False)

    async def mark_ready_for_assessment(self, uids: list[str]) -> None:
        """Advance deduplicated jobs to the fit-assessment stage."""
        if not uids:
            return
        await self._processing.update_many(
            {"uid": {"$in": uids}},
            {"$set": {"pipeline_stage": PipelineStage.DEDUPLICATED}},
        )

    async def remove_from_processing(self, uids: set[str]) -> None:
        """Remove jobs from the processing queue (e.g. deduplication drops)."""
        if not uids:
            return
        await self._processing.delete_many({"uid": {"$in": list(uids)}})

    async def store_failed(self, stage: str, failures: Sequence[FailedEntry]) -> None:
        """Record pipeline failures and remove the jobs from processing."""
        if not failures:
            return
        now = datetime.now(timezone.utc)
        failed_docs = []
        for failure in failures:
            if isinstance(failure, FailedJobPosting):
                entry = failure.posting.model_dump()
                uid = failure.posting.uid
                error = failure.error
            else:
                entry = failure.entry
                uid = entry.get("uid")
                error = failure.error
            failed_docs.append({
                "stage": stage,
                "uid": uid,
                "entry": entry,
                "error": error,
                "failed_at": now, })
        await self._failed.insert_many(failed_docs)

    async def get_user_profiles(self) -> list[UserProfile]:
        cursor = self._user_profiles.find()
        return [UserProfile.model_validate(doc) async for doc in cursor]

    async def store_processed_jobs(self, postings: Sequence[JobPosting]) -> None:
        if not postings:
            return
        await self._jobs.insert_many([posting.model_dump() for posting in postings])
