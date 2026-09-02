from pathlib import Path
from fastapi import APIRouter, Response

from api.deps import AppCurrentUser, AppJobsRepository, AppObjectStorage
from config import ConfigProvider
from logger_provider import LoggerProvider
from models.fit_assessment import CoverLetterContent
from models.jobs_api import JobFeedItem, JobFeedQuery, UpdateJobStatusRequest
from models.generics import PaginatedDataRequest, PaginatedDataResponse
from tools.pdf_generator import generate_cover_letter

router = APIRouter(prefix="/jobs", tags=["jobs"])
log = LoggerProvider.get_logger()
_TEMP_DIR = Path(ConfigProvider.get_config().TEMP_DIR)


@router.post("/search", response_model=PaginatedDataResponse[JobFeedItem])
async def get_jobs(
    request: PaginatedDataRequest[JobFeedQuery],
    user: AppCurrentUser,
    jobs_repository: AppJobsRepository,
) -> PaginatedDataResponse[JobFeedItem]:
    """
    Get all jobs.
    """
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
