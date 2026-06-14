from datetime import datetime, timezone
from typing import Sequence, Union

from pymongo import AsyncMongoClient, UpdateOne

from config import ConfigProvider
from models.collection_service import InvalidEntry, JobPosting
from models.deduplication import FailedJobPosting
from models.fit_assessment import FitAssessment
from models.generics import PaginatedDataRequest, PaginatedDataResponse
from models.job_application import ApplicationStage, JobApplicationStatus
from models.jobs_api import JobFeedItem, JobFeedQuery, JobFeedSortField, SortOrder, UpdateJobStatusRequest
from models.pipeline import PipelineStage
from models.users import UserProfile
from models.validators import ts_validator
from logger_provider import LoggerProvider

config = ConfigProvider.get_config()
log = LoggerProvider.get_logger()

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
        database: str | None = None,
    ) -> None:
        db = client[database or config.MONGODB_DATABASE]
        self._jobs = db[config.MONGODB_JOBS_COLLECTION]
        self._checkpoints = db[config.MONGODB_CHECKPOINTS_COLLECTION]
        self._processing = db[config.MONGODB_PROCESSING_COLLECTION]
        self._failed = db[config.MONGODB_FAILED_COLLECTION]
        self._user_profiles = db[config.MONGODB_USER_PROFILES_COLLECTION]
        self._assessments = db[config.MONGODB_ASSESSMENTS_COLLECTION]
        self._applications = db[config.MONGODB_JOB_APPLICATIONS_COLLECTION]

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

    async def store_many_assessments(self, assessments: list[tuple[FitAssessment, str, str]]) -> None:
        await self._assessments.insert_many([{
            "username": username,
            "job_uid": job_uid,
            "assessment": assessment.model_dump(mode="json"), } for assessment, username, job_uid in assessments])

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

    async def get_job_feed_items(
        self,
        request: PaginatedDataRequest[JobFeedQuery],
        username: str,
    ) -> PaginatedDataResponse[JobFeedItem]:
        """Return a paginated job feed for *username* by joining assessments, jobs, and application status."""
        pipeline = _build_job_feed_pipeline(request, username)
        log.info(f"Pipeline: {pipeline}")
        log.info(f"Length of pipeline: {len(pipeline)}")
        log.info(f"Pipeline: {pipeline[5]}")
        cursor = await self._assessments.aggregate(pipeline)
        result = await cursor.to_list(length=1)
        log.info(f"Result: {result}")
        if not result:
            return PaginatedDataResponse(data=[], page=request.page, page_size=request.page_size, total=0)

        facet = result[0]
        total = facet["metadata"][0]["total"] if facet["metadata"] else 0
        items = [_to_job_feed_item(doc, username) for doc in facet["data"]]

        return PaginatedDataResponse(data=items, page=request.page, page_size=request.page_size, total=total)

    async def insert_many_job_application_statuses(self, statuses: list[JobApplicationStatus]) -> None:
        await self._applications.insert_many([status.model_dump() for status in statuses])

    async def update_job_application_status(
        self,
        job_uid: str,
        username: str,
        request: UpdateJobStatusRequest,
    ) -> None:
        """Create or partially update the user's application status for *job_uid*."""
        if request.active is None and request.stage is None and request.skipped is None:
            return

        existing = await self._applications.find_one({"username": username, "job_uid": job_uid})
        defaults = JobApplicationStatus(username=username, job_uid=job_uid)
        current_active = existing["active"] if existing else defaults.active
        current_stage = ApplicationStage(existing["stage"]) if existing else defaults.stage
        current_skipped = existing.get("skipped", defaults.skipped) if existing else defaults.skipped

        await self._applications.update_one(
            {"username": username, "job_uid": job_uid},
            {
                "$set": {
                    "username": username,
                    "job_uid": job_uid,
                    "active": request.active if request.active is not None else current_active,
                    "stage": (request.stage if request.stage is not None else current_stage).value,
                    "skipped": request.skipped if request.skipped is not None else current_skipped, }},
            upsert=True,
        )


def _build_job_feed_pipeline(
    request: PaginatedDataRequest[JobFeedQuery],
    username: str,
) -> list[dict]:
    query = request.query
    sort_field = {
        JobFeedSortField.POSTED_AT: "job.posted_at",
        JobFeedSortField.CV_ATS_MATCH_SCORE: "assessment.cv_ats_match_score",
        JobFeedSortField.PROFILE_ATS_MATCH_SCORE: "assessment.profile_ats_match_score", }[query.sort_by]
    sort_direction = 1 if query.sort_order == SortOrder.ASC else -1
    skip = (request.page - 1) * request.page_size

    stages: list[dict] = [{"$match": {"username": username}}]

    assessment_match: dict = {}
    if query.min_cv_ats_match_score is not None:
        assessment_match["assessment.cv_ats_match_score"] = {"$gte": query.min_cv_ats_match_score}
    if query.min_profile_ats_match_score is not None:
        assessment_match["assessment.profile_ats_match_score"] = {"$gte": query.min_profile_ats_match_score}
    if query.exclude_deal_breakers:
        assessment_match["assessment.deal_breakers"] = {"$size": 0}
    if assessment_match:
        stages.append({"$match": assessment_match})

    stages.extend([
        {"$sort": {"_id": -1}},
        {"$group": {"_id": "$job_uid", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {
            "$lookup": {
                "from": config.MONGODB_JOBS_COLLECTION,
                "localField": "job_uid",
                "foreignField": "uid",
                "as": "job", }, },
        {"$unwind": "$job"}, ])

    job_match: dict = {}
    if query.remote is not None:
        job_match["job.remote"] = query.remote
    if query.sources:
        job_match["job.source"] = {"$in": query.sources}
    if query.tags:
        job_match["job.tags"] = {"$all": query.tags}
    if query.location:
        job_match["job.location"] = {"$regex": query.location, "$options": "i"}
    if job_match:
        stages.append({"$match": job_match})

    stages.extend([
        {
            "$lookup": {
                "from": config.MONGODB_JOB_APPLICATIONS_COLLECTION,
                "let": {"job_uid": "$job_uid"},
                "pipeline": [{
                    "$match": {
                        "$expr": {
                            "$and": [
                                {"$eq": ["$username", username]},
                                {"$eq": ["$job_uid", "$$job_uid"]}, ], }, }, }],
                "as": "application", }, },
        {
            "$addFields": {
                "has_application": {"$gt": [{"$size": "$application"}, 0]},
                "status_active": {"$arrayElemAt": ["$application.active", 0]},
                "status_stage": {"$arrayElemAt": ["$application.stage", 0]},
                "status_skipped": {
                    "$ifNull": [{"$arrayElemAt": ["$application.skipped", 0]}, False], }, }, }, ])

    application_match: dict = {}
    if query.active_only:
        application_match["has_application"] = True
        application_match["status_active"] = True
    if query.application_stage is not None:
        application_match["status_stage"] = query.application_stage.value
    if query.skipped:
        application_match["has_application"] = True
        application_match["status_skipped"] = True
    else:
        application_match["status_skipped"] = False
    if application_match:
        stages.append({"$match": application_match})

    stages.append({
        "$facet": {
            "metadata": [{"$count": "total"}],
            "data": [
                {"$sort": {sort_field: sort_direction}},
                {"$skip": skip},
                {"$limit": request.page_size}, ], }, })
    return stages


def _to_job_feed_item(doc: dict, username: str) -> JobFeedItem:
    status = None
    if doc.get("has_application"):
        status = JobApplicationStatus(
            username=username,
            job_uid=doc["job_uid"],
            active=doc["status_active"],
            stage=ApplicationStage(doc["status_stage"]),
            skipped=doc.get("status_skipped", False),
        )
    return JobFeedItem(
        job=JobPosting.model_validate(doc["job"]),
        fit=FitAssessment.model_validate(doc["assessment"]),
        status=status,
    )
