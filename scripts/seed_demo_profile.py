"""Upsert the demo user profile and CV into MongoDB and object storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pymongo import AsyncMongoClient

from agents.cv_text_extraction import CVTextExtractionAgent
from agents.model_factory import Model, ModelFactory
from config import ConfigProvider
from cv_text_service import ensure_cv_text
from demo import load_demo_profile
from logger_provider import LoggerProvider
from models.users import UserProfile
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage
from tools.cv_pdf import generate_cv_pdf

log = LoggerProvider.get_logger()


async def seed_demo_profile(
    *,
    expected_username: str,
    repository: MongoJobsRepository,
    object_storage: ObjectStorage,
    cv_text_extraction_agent: CVTextExtractionAgent,
    temp_dir: Path,
    profile: UserProfile | None = None,
) -> UserProfile:
    """Render the demo CV, upload it, upsert the profile document, and extract CV text.

    Re-running overwrites profile fields and the PDF. Assessments, screenings, and
    cover letters are left in place. ``$set`` of the profile dump does not unset
    derived ``cv_text`` fields; ``ensure_cv_text`` refreshes them when the PDF hash
    changes.
    """
    loaded = profile or load_demo_profile()
    if expected_username != loaded.username:
        raise SystemExit(
            f"DEMO_USERNAME={expected_username!r} does not match fixture username "
            f"{loaded.username!r}"
        )
    temp_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = temp_dir / "demo_cv.pdf"
    pages = generate_cv_pdf(loaded, str(pdf_path))
    cv_bytes = pdf_path.read_bytes()
    object_storage.upload_user_cv(loaded.username, str(pdf_path))
    await repository.upsert_user_profile(loaded)
    artifact = await ensure_cv_text(
        username=loaded.username,
        repository=repository,
        object_storage=object_storage,
        agent=cv_text_extraction_agent,
        cv_bytes=cv_bytes,
    )
    log.info(
        "Seeded demo profile {username} ({pages} page CV, cv_text_len={n})",
        username=loaded.username,
        pages=pages,
        n=len(artifact.cv_text),
    )
    return loaded


async def _async_main() -> None:
    """Load config, connect to Mongo, and seed the demo profile."""
    config = ConfigProvider.get_config()
    if not config.DEMO_USERNAME:
        raise SystemExit("DEMO_USERNAME is not set")
    mongo = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    try:
        await seed_demo_profile(
            expected_username=config.DEMO_USERNAME,
            repository=MongoJobsRepository(mongo),
            object_storage=ObjectStorage(),
            cv_text_extraction_agent=CVTextExtractionAgent(
                ModelFactory.get_model(Model(config.CV_EXTRACTION_MODEL))
            ),
            temp_dir=Path(config.TEMP_DIR),
        )
    finally:
        await mongo.close()


def main() -> None:
    """CLI entrypoint for ``seed-demo-profile``."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
