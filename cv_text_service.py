"""Freshness and persistence boundary for derived CV text."""

import hashlib

from agents.cv_text_extraction import CVTextExtractionAgent
from models.users import CVTextArtifact
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage


async def ensure_cv_text(
    *,
    username: str,
    repository: MongoJobsRepository,
    object_storage: ObjectStorage,
    agent: CVTextExtractionAgent,
    cv_bytes: bytes | None = None,
) -> CVTextArtifact:
    """Return fresh CV text, regenerating it when the source PDF digest changes."""
    if cv_bytes is None:
        cv_bytes = object_storage.get_user_cv(username)
    source_sha256 = hashlib.sha256(cv_bytes).hexdigest()
    existing = await repository.get_cv_text_artifact(username)
    if existing is not None and existing.source_sha256 == source_sha256:
        return existing

    cv_text = await agent.extract(cv_bytes)
    artifact = CVTextArtifact(cv_text=cv_text, source_sha256=source_sha256)
    await repository.store_cv_text_artifact(username, artifact)
    return artifact
