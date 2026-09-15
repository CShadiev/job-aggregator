"""Tests for CV rendering freshness and prompt packaging."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from cv_text_service import ensure_cv_text
from models.users import CVTextArtifact, UserProfile


@pytest.mark.asyncio
async def test_matching_pdf_digest_reuses_persisted_rendering():
    cv_bytes = b"%PDF-current"
    artifact = CVTextArtifact(
        cv_text="# Existing CV",
        source_sha256=hashlib.sha256(cv_bytes).hexdigest(),
    )
    repository = AsyncMock()
    repository.get_cv_text_artifact.return_value = artifact
    object_storage = MagicMock()
    object_storage.get_user_cv.return_value = cv_bytes
    agent = AsyncMock()

    result = await ensure_cv_text(
        username="ada",
        repository=repository,
        object_storage=object_storage,
        agent=agent,
    )

    assert result == artifact
    agent.extract.assert_not_awaited()
    repository.store_cv_text_artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_pdf_regenerates_and_persists_rendering():
    cv_bytes = b"%PDF-replaced"
    repository = AsyncMock()
    repository.get_cv_text_artifact.return_value = CVTextArtifact(
        cv_text="# Stale CV",
        source_sha256="0" * 64,
    )
    object_storage = MagicMock()
    object_storage.get_user_cv.return_value = cv_bytes
    agent = AsyncMock()
    agent.extract.return_value = "# Fresh CV"

    result = await ensure_cv_text(
        username="ada",
        repository=repository,
        object_storage=object_storage,
        agent=agent,
    )

    assert result.cv_text == "# Fresh CV"
    assert result.source_sha256 == hashlib.sha256(cv_bytes).hexdigest()
    agent.extract.assert_awaited_once_with(cv_bytes)
    repository.store_cv_text_artifact.assert_awaited_once_with("ada", result)


@pytest.mark.asyncio
async def test_missing_artifact_extracts_and_persists():
    """Verify a first read extracts when the profile has no derived CV text yet."""
    cv_bytes = b"%PDF-new"
    repository = AsyncMock()
    repository.get_cv_text_artifact.return_value = None
    object_storage = MagicMock()
    agent = AsyncMock()
    agent.extract.return_value = "# New CV"

    result = await ensure_cv_text(
        username="ada",
        repository=repository,
        object_storage=object_storage,
        agent=agent,
        cv_bytes=cv_bytes,
    )

    assert result.cv_text == "# New CV"
    object_storage.get_user_cv.assert_not_called()
    agent.extract.assert_awaited_once_with(cv_bytes)


def test_user_profile_dump_cannot_include_derived_cv_text():
    """Verify extra Mongo fields never leak through UserProfile.model_dump_json."""
    from tests.datasets.cover_letter_sample import make_sample_user_profile

    profile = make_sample_user_profile()
    doc = profile.model_dump()
    doc["cv_text"] = "SECRET-CV-TEXT"
    doc["cv_source_sha256"] = "a" * 64
    loaded = UserProfile.model_validate(doc)
    dumped = loaded.model_dump_json()
    assert "SECRET-CV-TEXT" not in dumped
    assert "cv_source_sha256" not in dumped
    assert "cv_text" not in loaded.model_dump()
