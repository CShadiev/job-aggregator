"""Cover letter generation shared by the pipeline subgraph and the manual HTTP trigger."""

from pathlib import Path

from agents.cover_letter_generation import CoverLetterGenerationAgent
from config import ConfigProvider
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.jobs_api import UpdateJobStatusRequest
from models.users import UserProfile
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage

log = LoggerProvider.get_logger()


async def generate_and_persist_cover_letter(
    *,
    username: str,
    job: JobPosting,
    assessment: FitAssessment,
    profile: UserProfile,
    agent: CoverLetterGenerationAgent,
    object_storage: ObjectStorage,
    repository: MongoJobsRepository,
) -> str:
    """Generate a cover letter, upload the JSON, and record the key on the job application.

    Returns:
        The object storage key of the uploaded cover letter JSON.
    """
    _log = log.bind(event="cover_letter_generate", username=username, job_uid=job.uid)
    file_path = Path(ConfigProvider.get_config().TEMP_DIR) / username / f"{job.uid}.json"
    try:
        _log.info("Generating cover letter")
        content = await agent.generate(profile, job, assessment)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content.model_dump_json(indent=2))
        object_key = object_storage.upload_coverletter_json(
            username=username,
            job_id=job.uid,
            file_path=str(file_path),
        )
        await repository.update_job_application_status(
            job_uid=job.uid,
            username=username,
            request=UpdateJobStatusRequest(cover_letter_key=object_key),
        )
        _log.info("Cover letter stored")
        return object_key
    finally:
        file_path.unlink(missing_ok=True)


async def run_cover_letter_generation_task(
    *,
    username: str,
    job_uid: str,
    repository: MongoJobsRepository,
    object_storage: ObjectStorage,
    agent: CoverLetterGenerationAgent,
) -> None:
    """Run a claimed manual generation task to completion, recording the outcome on the task.

    Never raises: the task document is the only channel a polling client has.
    """
    try:
        job = await repository.get_job(job_uid)
        if job is None:
            raise ValueError(f"Job not found: {job_uid}")
        profile = await repository.get_user_profile(username)
        if profile is None:
            raise ValueError(f"User profile not found: {username}")
        assessment = await repository.get_assessment(username, job_uid)
        if assessment is None:
            raise ValueError(f"Assessment not found for {username}/{job_uid}")

        await generate_and_persist_cover_letter(
            username=username,
            job=job,
            assessment=assessment,
            profile=profile,
            agent=agent,
            object_storage=object_storage,
            repository=repository,
        )
        await repository.complete_cover_letter_task(username, job_uid)
    except Exception as exc:
        await repository.fail_cover_letter_task(username, job_uid, error=str(exc))
        log.exception(
            "Manual cover letter generation failed for {username}/{job_uid}",
            event="cover_letter_task_error",
            username=username,
            job_uid=job_uid,
            exc_info=True,
        )
