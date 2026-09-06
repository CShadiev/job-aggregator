"""Dependency bundle for pipeline nodes."""

from dataclasses import dataclass

from aiohttp import ClientSession
from pymongo import AsyncMongoClient

from agents.cover_letter_generation import CoverLetterGenerationAgent
from agents.deduplication import DeduplicationAgent
from agents.fit_assessment import FitAssessmentAgent
from agents.model_factory import Model, ModelFactory
from agents.screening import ScreeningAgent
from collection_service.apify_collector import ApifyCollector
from collection_service.arbeitnow_collector import ArbeitnowCollector
from collection_service.collection_service import CollectionService
from collection_service.linkedin_apify_parser import LinkedinApifyParser
from config import Config, ConfigProvider
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage
from search.client import build_opensearch_client
from search.embeddings import EmbeddingClient
from search.search_service import SearchService


@dataclass
class PipelineDeps:
    """Encapsulates all clients, repositories, agents, and configuration required by pipeline nodes."""

    collection_service: CollectionService
    repository: MongoJobsRepository
    object_storage: ObjectStorage
    screening_agent: ScreeningAgent
    fit_assessment_agent: FitAssessmentAgent
    cover_letter_agent: CoverLetterGenerationAgent
    cover_letter_min_cv_score: float
    screening_model: str
    thread_id: str
    client_session: ClientSession
    async_mongo_client: AsyncMongoClient
    search_service: SearchService
    embedding_client: EmbeddingClient
    pair_mode: str
    retrieval_k: int


def build_collectors(client_session: ClientSession, config: Config) -> list:
    """Instantiate and return list of scrapers and API collectors configured for the pipeline.

    Args:
        client_session: Shared aiohttp ClientSession.
        config: Application configuration.

    Returns:
        List of configured ICollector implementations.
    """
    return [
        ApifyCollector(
            client_session=client_session,
            task_id=config.APIFY_LINKEDIN_TASK_ID,
            source_tag="linkedin",
            apify_parser=LinkedinApifyParser(source_tag="linkedin"),
            run_apify_task=False,
        ),
        ApifyCollector(
            client_session=client_session,
            task_id=config.APIFY_LINKEDIN_PL_TASK_ID,
            source_tag="linkedin-poland",
            apify_parser=LinkedinApifyParser(source_tag="linkedin-poland"),
            run_apify_task=False,
        ),
        ApifyCollector(
            client_session=client_session,
            task_id=config.APIFY_LINKEDIN_UK_TASK_ID,
            source_tag="linkedin-united-kingdom",
            apify_parser=LinkedinApifyParser(source_tag="linkedin-united-kingdom"),
            run_apify_task=False,
        ),
        ArbeitnowCollector(client=client_session),
    ]


async def build_deps(
    *,
    async_mongo_client: AsyncMongoClient,
    client_session: ClientSession,
    config: Config | None = None,
) -> PipelineDeps:
    """Construct and assemble all PipelineDeps dependencies.

    Args:
        async_mongo_client: Asynchronous MongoDB client.
        client_session: Shared aiohttp ClientSession.
        config: Optional Config instance override.

    Returns:
        Fully initialized PipelineDeps container.
    """
    cfg = config or ConfigProvider.get_config()
    search_service = SearchService(build_opensearch_client(cfg), config=cfg)
    embedding_client = EmbeddingClient(client_session, config=cfg)
    repository = MongoJobsRepository(async_mongo_client, search_service=search_service)
    deduplication_model = Model(cfg.DEDUPLICATION_MODEL)
    screening_model = Model(cfg.SCREENING_MODEL)
    fit_assessment_model = Model(cfg.FIT_ASSESSMENT_MODEL)
    cover_letter_model = Model(cfg.COVER_LETTER_MODEL)
    deduplication_agent = DeduplicationAgent(ModelFactory.get_model(deduplication_model))
    collection_service = CollectionService(
        collectors=build_collectors(client_session, cfg),
        repo=repository,
        agent=deduplication_agent,
    )
    return PipelineDeps(
        collection_service=collection_service,
        repository=repository,
        object_storage=ObjectStorage(),
        screening_agent=ScreeningAgent(ModelFactory.get_model(screening_model)),
        fit_assessment_agent=FitAssessmentAgent(ModelFactory.get_model(fit_assessment_model)),
        cover_letter_agent=CoverLetterGenerationAgent(ModelFactory.get_model(cover_letter_model)),
        cover_letter_min_cv_score=cfg.COVER_LETTER_MIN_CV_SCORE,
        screening_model=screening_model.value,
        thread_id=cfg.PIPELINE_THREAD_ID,
        client_session=client_session,
        async_mongo_client=async_mongo_client,
        search_service=search_service,
        embedding_client=embedding_client,
        pair_mode=cfg.PIPELINE_PAIR_MODE,
        retrieval_k=cfg.PIPELINE_RETRIEVAL_K,
    )
