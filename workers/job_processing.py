import asyncio
from pathlib import Path
from aiohttp import ClientSession
from agents.cover_letter_generation import CoverLetterGenerationAgent
from collection_service.collection_service import CollectionService
from collection_service.apify_collector import ApifyCollector
from collection_service.arbeitnow_collector import ArbeitnowCollector
from collection_service.linkedin_apify_parser import LinkedinApifyParser
from models.generics import PaginatedDataRequest
from models.jobs_api import JobFeedItem, JobFeedQuery, UpdateJobStatusRequest
from models.users import UserProfile
from repository.mongo_jobs_repository import MongoJobsRepository
from agents.deduplication import DeduplicationAgent
from agents.fit_assessment import FitAssessmentAgent
from agents.model_factory import Model, ModelFactory
from config import ConfigProvider

from pymongo import AsyncMongoClient
from logger_provider import LoggerProvider

from repository.object_storage import ObjectStorage

config = ConfigProvider.get_config()
log = LoggerProvider.get_logger()


async def collect_jobs(repository: MongoJobsRepository, collection_service: CollectionService):

    result = await collection_service.collect()
    log.info(f"Collected {len(result.postings)} jobs")
    if result.postings:
        await repository.store_in_processing(result.postings)
        log.info(f"Stored {len(result.postings)} jobs in processing")

    if result.invalid_entries:
        await repository.store_failed(stage="collection", failures=result.invalid_entries)
        log.info(f"Failed to parse {len(result.invalid_entries)} jobs")


async def normalize_jobs(repository: MongoJobsRepository, collection_service: CollectionService):
    for i in range(10):
        postings = await repository.get_normalization_feed()
        result = await collection_service.normalize(postings)

        if not result.processed and not result.failed:
            log.info("No jobs to normalize")
            return

        if result.processed:
            log.info(f"Normalized {len(result.processed)} jobs")
            await repository.save_normalized_results(result.processed)

        if result.failed:
            log.info(f"Failed to normalize {len(result.failed)} jobs")
            await repository.store_failed(stage="normalization", failures=result.failed)


async def deduplicate_jobs(repository: MongoJobsRepository, collection_service: CollectionService):
    postings = await repository.get_deduplication_feed()
    log.info(f"Deduplicating {len(postings)} jobs")
    unique_postings = await collection_service.deduplicate(postings)
    duplicated_postings = [p for p in postings if p.uid not in [p.uid for p in unique_postings]]
    log.info(
        "Removed {n_duplicated_jobs} duplicated jobs from processing, {n_unique_jobs} unique jobs remaining",
        event="deduplicated_jobs", n_duplicated_jobs=len(duplicated_postings),
        n_unique_jobs=len(unique_postings))
    await repository.remove_from_processing(set([p.uid for p in duplicated_postings]))
    await repository.mark_ready_for_assessment([p.uid for p in unique_postings])


async def assess_jobs(
        repository: MongoJobsRepository, fit_assessment_agent: FitAssessmentAgent,
        object_storage: ObjectStorage):

    user_profiles = await repository.get_user_profiles()
    postings = await repository.get_assessment_feed(limit=100)

    for user_profile in user_profiles:
        log.info(f"Assessing {len(postings)} jobs for user {user_profile.username}")
        cv = object_storage.get_user_cv(user_profile.username)
        cv_dir = Path("tmp") / Path(user_profile.username)
        cv_dir.mkdir(parents=True, exist_ok=True)
        cv_file = cv_dir / "cv.pdf"
        cv_file.write_bytes(cv)
        log.info(f"Assessing CV for user {user_profile.username}")
        semaphore = asyncio.Semaphore(10)
        async with semaphore:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(
                        fit_assessment_agent.assess(
                            user_profile=user_profile, job=posting, cv=cv_file))
                    for posting in postings]

            assessments = [task.result() for task in tasks]
            for assessment, posting in zip(assessments, postings):
                await repository.store_assessment(assessment, user_profile.username, posting.uid)

        cv_file.unlink()
        await repository.store_processed_jobs(postings)
        await repository.remove_from_processing(set([p.uid for p in postings]))
        log.info(
            "Assessed {n_assessed_jobs} jobs for user {username}, {n_high_fit_jobs} jobs with fit score >= 80",
            n_assessed_jobs=len(assessments), username=user_profile.username,
            n_high_fit_jobs=len([a for a in assessments
                                 if a.profile_ats_match_score >= 80]), event="assessed_jobs")


async def _generate_cover_letter_task(
        agent: CoverLetterGenerationAgent, job: JobFeedItem, object_storage: ObjectStorage,
        user_profile: UserProfile, repository: MongoJobsRepository):
    _log = log.bind(event="generate_cover_letter", job_uid=job.job.uid)
    _log.info("Generating cover letter")
    cover_letter = await agent.generate(user_profile, job.job, job.fit)
    _log.info("Cover letter generated")
    file_path = Path("tmp") / Path(user_profile.username) / f"{job.job.uid}.json"
    try:
        _log.info("Storing cover letter")
        file_path.write_text(cover_letter.model_dump_json(indent=2))
        object_key = object_storage.upload_coverletter_json(
            username=user_profile.username, job_id=job.job.uid, file_path=str(file_path))
        _log.info("Cover letter stored")
        await repository.update_job_application_status(
            job_uid=job.job.uid, username=user_profile.username,
            request=UpdateJobStatusRequest(cover_letter_key=object_key))
        _log.info("Job application status updated")
    except Exception as e:
        _log.exception("Error updating job application status", exc_info=True)
        raise e
    finally:
        file_path.unlink()
        _log.info("Cover letter file deleted")


async def generate_cover_letters(repository: MongoJobsRepository, object_storage: ObjectStorage):
    agent = CoverLetterGenerationAgent(model=ModelFactory.get_model(Model.GROK_4_5))
    semaphore = asyncio.Semaphore(10)
    user_profiles = await repository.get_user_profiles()
    for user_profile in user_profiles:
        log.info(f"Generating cover letters for user {user_profile.username}")
        paginated_data = await repository.get_job_feed_items(
            PaginatedDataRequest(
                query=JobFeedQuery(min_cv_ats_match_score=80, applied=False), page_size=100),
            username=user_profile.username)
        jobs = [
            job for job in paginated_data.data
            if job.status and job.status.cover_letter_key is None]
        log.info(f"Generating cover letters for {len(jobs)} jobs")
        async with semaphore:
            tasks = [
                _generate_cover_letter_task(agent, job, object_storage, user_profile, repository)
                for job in jobs]
            await asyncio.gather(*tasks)


async def main():

    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST, port=config.MONGODB_PORT, username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD)
    repository = MongoJobsRepository(mongo_client)

    deduplication_agent = DeduplicationAgent(ModelFactory.get_model(Model.GROK_4_3))
    fit_assessment_agent = FitAssessmentAgent(ModelFactory.get_model(Model.GROK_4_3))
    object_storage = ObjectStorage()

    async with ClientSession() as client_session:
        collectors = [
            ApifyCollector(
                client_session=client_session, task_id=config.APIFY_LINKEDIN_TASK_ID,
                source_tag="linkedin", apify_parser=LinkedinApifyParser(source_tag="linkedin"),
                run_apify_task=False),
            ApifyCollector(
                client_session=client_session, task_id=config.APIFY_LINKEDIN_PL_TASK_ID,
                source_tag="linkedin-poland",
                apify_parser=LinkedinApifyParser(source_tag="linkedin-poland"),
                run_apify_task=False),
            ApifyCollector(
                client_session=client_session, task_id=config.APIFY_LINKEDIN_UK_TASK_ID,
                source_tag="linkedin-united-kingdom",
                apify_parser=LinkedinApifyParser(source_tag="linkedin-united-kingdom"),
                run_apify_task=False),
            ArbeitnowCollector(client=client_session), ]
        collection_service = CollectionService(
            collectors=collectors, repo=repository, agent=deduplication_agent)
        await collect_jobs(repository, collection_service)
        await normalize_jobs(repository, collection_service)
        await deduplicate_jobs(repository, collection_service)
        await assess_jobs(repository, fit_assessment_agent, object_storage)
        await generate_cover_letters(repository, object_storage)


if __name__ == "__main__":
    import time
    log.info(
        "{service}: Starting job processing", service="main_worker", event="started", success=1)
    try:
        while True:
            asyncio.run(main())
            time.sleep(60 * 60 * 12)
    except Exception as e:
        log.exception(
            "{service}: Error in job processing", service="main_worker", event="error", success=0,
            exc_info=True)
        raise e
