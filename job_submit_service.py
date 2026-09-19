"""Manual job submission: normalise, persist, assess, and generate a cover letter."""

from datetime import UTC, datetime

from agents.cover_letter_generation import CoverLetterGenerationAgent
from agents.cv_text_extraction import CVTextExtractionAgent
from agents.deduplication import DeduplicationAgent
from agents.fit_assessment import FitAssessmentAgent
from cover_letter_service import generate_and_persist_cover_letter
from cv_text_service import ensure_cv_text
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.jobs_api import ManualJobSubmitRequest
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage

log = LoggerProvider.get_logger()

MANUAL_JOB_SOURCE = "manual"


def posting_from_submit_request(request: ManualJobSubmitRequest) -> JobPosting:
    """Build a ``JobPosting`` from a submit request. Normalised fields are filled later."""
    now = datetime.now(UTC)
    return JobPosting(
        uid=str(request.job_uid),
        source=MANUAL_JOB_SOURCE,
        title=request.title,
        company=request.company,
        location=request.location,
        remote=request.remote,
        url=request.url,
        tags=list(request.tags),
        description_raw=request.description_raw,
        job_types=list(request.job_types),
        posted_at=request.posted_at or now,
        collected_at=now,
    )


async def run_manual_job_submit_task(
    *,
    username: str,
    request: ManualJobSubmitRequest,
    repository: MongoJobsRepository,
    object_storage: ObjectStorage,
    deduplication_agent: DeduplicationAgent,
    fit_assessment_agent: FitAssessmentAgent,
    cv_text_extraction_agent: CVTextExtractionAgent,
    cover_letter_agent: CoverLetterGenerationAgent,
) -> None:
    """Run a claimed manual submit to completion, recording the outcome on the task.

    Never raises: the task document is the only channel a polling client has.
    """
    job_uid = str(request.job_uid)
    try:
        posting = posting_from_submit_request(request)
        result = await deduplication_agent.normalize([posting])
        if not result.processed:
            error = result.failed[0].error if result.failed else "Normalization returned no result"
            raise ValueError(error)
        posting = result.processed[0]
        await repository.upsert_jobs([posting])

        assessment = await repository.get_assessment(username, job_uid)
        if assessment is None:
            profile = await repository.get_user_profile(username)
            if profile is None:
                raise ValueError(f"User profile not found: {username}")
            cv_text = (
                await ensure_cv_text(
                    username=username,
                    repository=repository,
                    object_storage=object_storage,
                    agent=cv_text_extraction_agent,
                )
            ).cv_text
            assessment = await fit_assessment_agent.assess(
                user_profile=profile,
                cv_text=cv_text,
                job=posting,
            )
            await repository.store_assessment(assessment, username, job_uid, job=posting)

        if not await repository.get_application_cover_letter_key(username, job_uid):
            profile = await repository.get_user_profile(username)
            if profile is None:
                raise ValueError(f"User profile not found: {username}")
            await generate_and_persist_cover_letter(
                username=username,
                job=posting,
                assessment=assessment,
                profile=profile,
                agent=cover_letter_agent,
                object_storage=object_storage,
                repository=repository,
            )

        await repository.complete_manual_job_task(username, job_uid)
    except Exception as exc:
        log.exception(
            "Manual job submit failed for {username}/{job_uid}",
            event="manual_job_submit_task_error",
            username=username,
            job_uid=job_uid,
        )
        await repository.fail_manual_job_task(username, job_uid, error=str(exc))
