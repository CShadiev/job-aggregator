"""HTTP endpoints for job feed search, application status updates, and cover letter retrieval."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from api.deps import (
    AppCoverLetterAgent,
    AppCurrentUser,
    AppJobsRepository,
    AppObjectStorage,
    AppSearchService,
)
from config import ConfigProvider
from cover_letter_service import run_cover_letter_generation_task
from logger_provider import LoggerProvider
from models.cover_letter_task import CoverLetterTask, CoverLetterTaskStatus
from models.fit_assessment import CoverLetterContent
from models.generics import PaginatedDataRequest, PaginatedDataResponse
from models.jobs_api import (
    CoverLetterGenerationStatus,
    CoverLetterGenerationStatusResponse,
    JobFeedItem,
    JobFeedQuery,
    UpdateJobStatusRequest,
)
from tools.pdf_generator import generate_cover_letter

router = APIRouter(prefix="/jobs", tags=["jobs"])
log = LoggerProvider.get_logger()
config = ConfigProvider.get_config()
_TEMP_DIR = Path(config.TEMP_DIR)


@router.post("/search", response_model=PaginatedDataResponse[JobFeedItem])
async def get_jobs(
    request: PaginatedDataRequest[JobFeedQuery],
    user: AppCurrentUser,
    jobs_repository: AppJobsRepository,
    search_service: AppSearchService,
) -> PaginatedDataResponse[JobFeedItem]:
    """
    Personalized assessed-job feed with optional keyword search ``q``.
    """
    try:
        return await search_service.search_user_feed(
            username=user.username,
            query=request.query,
            page=request.page,
            page_size=request.page_size,
        )
    except Exception:
        log.exception(
            "OpenSearch feed query failed; falling back to MongoDB",
            event="jobs_search_fallback",
            username=user.username,
        )
        return await jobs_repository.get_job_feed_items(request, user.username)


@router.patch("/{job_uid}/status")
async def update_job_status(
    job_uid: str,
    request: UpdateJobStatusRequest,
    user: AppCurrentUser,
    jobs_repository: AppJobsRepository,
) -> None:
    """
    Update the status of a job.
    """
    await jobs_repository.update_job_application_status(job_uid, user.username, request)


@router.get("/{job_uid}/cover-letter")
async def get_cover_letter(
    job_uid: str, user: AppCurrentUser, object_storage: AppObjectStorage
) -> CoverLetterContent:
    """
    Get the cover letter for a job.
    """
    json_file = _TEMP_DIR / "cover_letter.json"
    try:
        json_path = object_storage.get_coverletter_json(user.username, job_uid, str(json_file))
        return CoverLetterContent.model_validate_json(Path(json_path).read_text())
    finally:
        json_file.unlink(missing_ok=True)


@router.get("/{job_uid}/cover-letter-pdf")
async def get_cover_letter_pdf(
    job_uid: str, user: AppCurrentUser, object_storage: AppObjectStorage
) -> Response:
    """
    Get the cover letter PDF for a job.
    """
    json_file = _TEMP_DIR / "cover_letter.json"
    pdf_file = _TEMP_DIR / "cover_letter.pdf"
    try:
        json_path = object_storage.get_coverletter_json(user.username, job_uid, str(json_file))
        cover_letter_content = CoverLetterContent.model_validate_json(Path(json_path).read_text())
        generate_cover_letter(cover_letter_content, str(pdf_file))
        return Response(content=pdf_file.read_bytes(), media_type="application/pdf")
    finally:
        json_file.unlink(missing_ok=True)
        pdf_file.unlink(missing_ok=True)


def _reportable_status(task: CoverLetterTask | None) -> CoverLetterGenerationStatus | None:
    """Map a stored task to the status to report, or None when the task may be claimed again.

    A pending task past its expiry and a failed task are both claimable: the process that
    owned the run is gone or the run errored, so the next request restarts generation.
    """
    if task is None:
        return None
    if task.status == CoverLetterTaskStatus.COMPLETE:
        return CoverLetterGenerationStatus.COMPLETE
    if task.status == CoverLetterTaskStatus.PENDING and task.expires_at > datetime.now(UTC):
        return CoverLetterGenerationStatus.PENDING
    return None


@router.post("/{job_uid}/cover-letter/generate")
async def generate_job_cover_letter(
    job_uid: str,
    background_tasks: BackgroundTasks,
    user: AppCurrentUser,
    jobs_repository: AppJobsRepository,
    object_storage: AppObjectStorage,
    cover_letter_agent: AppCoverLetterAgent,
) -> CoverLetterGenerationStatusResponse:
    """
    Start cover letter generation for a job, or report the status of a request already running.

    Generation happens in the background; poll this endpoint until it reports ``complete``.
    Jobs the pipeline already generated a letter for report ``complete`` immediately.
    """
    username = user.username
    _log = log.bind(event="cover_letter_generate_request", username=username, job_uid=job_uid)

    assessment = await jobs_repository.get_assessment(username, job_uid)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Job has not been assessed for this user")

    if await jobs_repository.get_application_cover_letter_key(username, job_uid):
        return CoverLetterGenerationStatusResponse(status=CoverLetterGenerationStatus.COMPLETE)

    existing = await jobs_repository.get_cover_letter_task(username, job_uid)
    reportable = _reportable_status(existing)
    if reportable is not None:
        return CoverLetterGenerationStatusResponse(status=reportable)

    # Fail before promising a pending task the background run could not fulfil.
    if await jobs_repository.get_job(job_uid) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if await jobs_repository.get_user_profile(username) is None:
        raise HTTPException(status_code=404, detail="User profile not found")

    claimed = await jobs_repository.claim_pending_cover_letter_task(
        username, job_uid, ttl_seconds=config.COVER_LETTER_TASK_TTL_SECONDS
    )
    if claimed is None:
        # A concurrent request won the claim; report whatever it left behind.
        current = _reportable_status(await jobs_repository.get_cover_letter_task(username, job_uid))
        return CoverLetterGenerationStatusResponse(
            status=current or CoverLetterGenerationStatus.PENDING
        )

    background_tasks.add_task(
        run_cover_letter_generation_task,
        username=username,
        job_uid=job_uid,
        repository=jobs_repository,
        object_storage=object_storage,
        agent=cover_letter_agent,
    )
    _log.info("Cover letter generation scheduled")
    return CoverLetterGenerationStatusResponse(status=CoverLetterGenerationStatus.PENDING)


@router.patch("/{job_uid}/cover-letter")
async def update_cover_letter(
    job_uid: str,
    user: AppCurrentUser,
    object_storage: AppObjectStorage,
    cover_letter_content: CoverLetterContent,
) -> None:
    """
    Update the cover letter for a job.
    """
    file_path = _TEMP_DIR / f"{job_uid}_cover_letter.json"
    try:
        file_path.write_text(cover_letter_content.model_dump_json())
        object_storage.upload_coverletter_json(user.username, job_uid, str(file_path))
    finally:
        file_path.unlink(missing_ok=True)
