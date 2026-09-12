"""
This module is the entry point for the FastAPI application.
It sets up the app instance, configures the lifespan, and includes the API routers.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from pymongo import AsyncMongoClient

from agents.cover_letter_generation import CoverLetterGenerationAgent
from agents.model_factory import Model, ModelFactory
from api.middleware.correlation import CorrelationIdMiddleware
from api.middleware.metrics import PrometheusMiddleware
from api.routes import health, jobs, metrics, users
from auth_service import Auth0ClientWrapper
from config import ConfigProvider
from logger_provider import LoggerProvider
from monitoring.pricing import configure_pricing
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage
from search.client import build_opensearch_client
from search.search_service import SearchService
from telemetry import instrument_fastapi, setup_telemetry

log = LoggerProvider.get_logger()
config = ConfigProvider.get_config()

# Initialize OpenTelemetry tracing & auto-instrumentation
setup_telemetry()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Manages the application lifespan, initializing the API container on startup.
    The initialized API instance is made available to request handlers via request.state.
    """
    log.info("Starting FastAPI application")
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    configure_pricing(mongo_client, config=config)
    auth0_client = Auth0ClientWrapper(config)
    search_service = SearchService(build_opensearch_client(config), config=config)
    try:
        await search_service.ensure_indices()
    except Exception as exc:
        log.warning("OpenSearch index bootstrap failed: {exc}", exc=str(exc))
    jobs_repository = MongoJobsRepository(mongo_client, search_service=search_service)
    await jobs_repository.ensure_cover_letter_task_indexes()
    object_storage = ObjectStorage()
    cover_letter_agent = CoverLetterGenerationAgent(
        ModelFactory.get_model(Model(config.COVER_LETTER_MODEL))
    )
    Path(config.TEMP_DIR).mkdir(parents=True, exist_ok=True)
    log.info("Dependencies initialized, application ready")
    yield {
        "jobs_repository": jobs_repository,
        "auth0_client": auth0_client,
        "object_storage": object_storage,
        "search_service": search_service,
        "cover_letter_agent": cover_letter_agent,
    }
    log.info("FastAPI application shutting down")
    await search_service.close()


metrics_middleware = [Middleware(PrometheusMiddleware)] if config.METRICS_ENABLED else []

middleware = [
    Middleware(CorrelationIdMiddleware),
    *metrics_middleware,
    Middleware(
        CORSMiddleware,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_headers=["*"],
    ),
]

# Initialize the FastAPI application with our custom lifespan manager.
app = FastAPI(lifespan=lifespan, middleware=middleware)

# Instrument FastAPI with OpenTelemetry
instrument_fastapi(app)

# Register the API routers for different functional areas.
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(users.router)

if config.METRICS_ENABLED:
    app.include_router(metrics.router)
