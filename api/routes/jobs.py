from fastapi import APIRouter

from api.deps import AppCurrentUser, AppJobsRepository
from logger_provider import LoggerProvider
from models.jobs_api import JobFeedItem, JobFeedQuery, UpdateJobStatusRequest
from models.generics import PaginatedDataRequest, PaginatedDataResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])
log = LoggerProvider.get_logger()


@router.post("/search", response_model=PaginatedDataResponse[JobFeedItem])
async def get_jobs(
        request: PaginatedDataRequest[JobFeedQuery], user: AppCurrentUser,
        jobs_repository: AppJobsRepository) -> PaginatedDataResponse[JobFeedItem]:
    """
    Get all jobs.
    """
    return await jobs_repository.get_job_feed_items(request, user.username)


@router.patch("/{job_uid}/status")
async def update_job_status(
        job_uid: str, request: UpdateJobStatusRequest, user: AppCurrentUser,
        jobs_repository: AppJobsRepository) -> None:
    """
    Update the status of a job.
    """
    await jobs_repository.update_job_application_status(job_uid, user.username, request)
