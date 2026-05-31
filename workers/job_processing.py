import asyncio
from pathlib import Path
from aiohttp import ClientSession
from collection_service.collection_service import CollectionService
from collection_service.apify_collector import ApifyCollector
from collection_service.arbeitnow_collector import ArbeitnowCollector
from collection_service.indeed_apify_parser import IndeedApifyParser
from collection_service.stepstone_parser import StepstoneParser
from repository.mongo_jobs_repository import MongoJobsRepository
from agents.deduplication import DeduplicationAgent
from agents.fit_assessment import FitAssessmentAgent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
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
    postings = await repository.get_normalization_feed()
    result = await collection_service.normalize(postings)
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
    await repository.remove_from_processing(set([p.uid for p in duplicated_postings]))
    log.info(f"Removed {len(duplicated_postings)} duplicated jobs from processing")
    await repository.mark_ready_for_assessment([p.uid for p in unique_postings])
    log.info(f"Marked {len(unique_postings)} jobs as ready for assessment")


async def assess_jobs(
        repository: MongoJobsRepository, fit_assessment_agent: FitAssessmentAgent, object_storage: ObjectStorage):

    user_profiles = await repository.get_user_profiles()
    postings = await repository.get_assessment_feed()

    for user_profile in user_profiles:
        log.info(f"Assessing {len(postings)} jobs for user {user_profile.username}")
        cv = object_storage.get_user_cv(user_profile.username)
        cv_dir = Path("tmp") / Path(user_profile.username)
        cv_dir.mkdir(parents=True, exist_ok=True)
        cv_file = cv_dir / "cv.pdf"
        cv_file.write_bytes(cv)
        log.info(f"Assessing CV for user {user_profile.username}")
        for posting in postings:
            assessment = await fit_assessment_agent.assess(user_profile=user_profile, job=posting, cv=cv_file)
            await repository.store_assessment(assessment, user_profile.username, posting.uid)
        cv_file.unlink()

    await repository.remove_from_processing(set([p.uid for p in postings]))
    log.info(f"Removed {len(postings)} jobs from processing")


async def main():

    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST, port=config.MONGODB_PORT, username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD)
    repository = MongoJobsRepository(mongo_client)

    model = OpenAIChatModel(model_name="gpt-5-mini", provider=OpenAIProvider(api_key=config.OPENAI_API_KEY))
    deduplication_agent = DeduplicationAgent(model)
    fit_assessment_agent = FitAssessmentAgent(model)
    object_storage = ObjectStorage()

    async with ClientSession() as client_session:
        collectors = [
            ApifyCollector(
                client_session=client_session, task_id=config.APIFY_INDEED_TASK_ID, source_tag="indeed",
                apify_parser=IndeedApifyParser(source_tag="indeed"), run_apify_task=False),
            ApifyCollector(
                client_session=client_session, task_id=config.APIFY_STEPSTONE_TASK_ID, source_tag="stepstone",
                apify_parser=StepstoneParser(source_tag="stepstone"), run_apify_task=False),
            ArbeitnowCollector(client=client_session), ]
        collection_service = CollectionService(collectors=collectors, repo=repository, agent=deduplication_agent)
        await collect_jobs(repository, collection_service)
        await normalize_jobs(repository, collection_service)
        await deduplicate_jobs(repository, collection_service)
        await assess_jobs(repository, fit_assessment_agent, object_storage)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        log.error(f"Error: {e}")
        raise e
