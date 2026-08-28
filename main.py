"""
This module is the entry point for the FastAPI application.
It sets up the app instance, configures the lifespan, and includes the API routers.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from config import ConfigProvider
from auth_service import Auth0ClientWrapper
from pymongo import AsyncMongoClient
from logger_provider import LoggerProvider

from api.routes import jobs
from api.routes import users
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage

log = LoggerProvider.get_logger()

config = ConfigProvider.get_config()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Manages the application lifespan, initializing the API container on startup.
    The initialized API instance is made available to request handlers via request.state.
    """
    log.info("Starting FastAPI application")
    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST, port=config.MONGODB_PORT, username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD)
    auth0_client = Auth0ClientWrapper(config)
    jobs_repository = MongoJobsRepository(mongo_client)
    object_storage = ObjectStorage()
    Path(config.TEMP_DIR).mkdir(parents=True, exist_ok=True)
    log.info("Dependencies initialized, application ready")
    yield {
        "jobs_repository": jobs_repository, "auth0_client": auth0_client,
        "object_storage": object_storage}
    log.info("FastAPI application shutting down")


middleware = [
    Middleware(
        CORSMiddleware,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_headers=["*"],
    ), ]

# Initialize the FastAPI application with our custom lifespan manager.
# root_path tells FastAPI it's mounted behind a proxy that already stripped
# a prefix (e.g. Gateway API URLRewrite stripping "/api") — needed so
# generated OpenAPI/docs URLs and redirects account for the real external
# path instead of assuming they're served from "/".
app = FastAPI(lifespan=lifespan, middleware=middleware, root_path=config.FASTAPI_ROOT_PATH)
# Register the API routers for different functional areas.
app.include_router(jobs.router)
app.include_router(users.router)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Shallow liveness/readiness probe target.

    Deliberately does not ping Mongo/Auth0/etc: a slow dependency should not
    flap the pod's readiness (and therefore drop it from the Service) just
    because a downstream is briefly slow. Revisit with a real dependency
    check once there's a reason to distinguish "process is up" from
    "process can actually serve traffic".
    """
    return {"status": "ok"}
