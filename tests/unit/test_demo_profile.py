"""Tests for the committed demo profile fixture, CV PDF, and profile seed."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from demo import DEMO_PROFILE_PATH, load_demo_profile
from models.users import CVTextArtifact, UserProfile
from repository.mongo_jobs_repository import MongoJobsRepository
from scripts.seed_demo_profile import seed_demo_profile
from tools.cv_pdf import generate_cv_pdf


def test_demo_profile_fixture_is_a_valid_user_profile():
    """The committed fixture must validate as UserProfile with username demo."""
    profile = load_demo_profile()
    assert profile.username == "demo"
    assert DEMO_PROFILE_PATH.name == "profile.json"
    dumped = UserProfile.model_validate_json(DEMO_PROFILE_PATH.read_text(encoding="utf-8"))
    assert dumped.username == "demo"
    assert dumped.profile.contact.email.endswith("@example.com")


def test_demo_profile_contains_no_author_identifiers():
    """The public demo biography must not mention the repository author's account."""
    text = DEMO_PROFILE_PATH.read_text(encoding="utf-8").lower()
    assert "cshadiev" not in text
    profile = load_demo_profile()
    assert "cshadiev" not in profile.profile.name.lower()
    assert "cshadiev" not in profile.profile.contact.email.lower()


def test_generate_cv_pdf_writes_a_multi_page_pdf(tmp_path: Path):
    """The seed CV must be a real PDF long enough to span more than one page."""
    output = tmp_path / "cv.pdf"
    pages = generate_cv_pdf(load_demo_profile(), str(output))
    assert pages >= 2
    assert output.read_bytes().startswith(b"%PDF")


@pytest.mark.asyncio
async def test_upsert_user_profile_sets_prompt_fields_without_unsetting_cv_text():
    """A profile upsert is $set of UserProfile.model_dump, never $unset of derived CV fields."""
    repo = MongoJobsRepository.__new__(MongoJobsRepository)
    repo._user_profiles = AsyncMock()
    profile = load_demo_profile()

    await MongoJobsRepository.upsert_user_profile(repo, profile)

    repo._user_profiles.update_one.assert_awaited_once()
    filter_doc, update_doc = repo._user_profiles.update_one.await_args.args
    assert filter_doc == {"username": "demo"}
    assert repo._user_profiles.update_one.await_args.kwargs["upsert"] is True
    assert "$unset" not in update_doc
    assert set(update_doc["$set"]) == set(profile.model_dump())
    assert "cv_text" not in update_doc["$set"]
    assert "cv_source_sha256" not in update_doc["$set"]


@pytest.mark.asyncio
async def test_seed_demo_profile_refuses_username_mismatch(tmp_path: Path):
    """The operator env username must match the fixture or the seed aborts."""
    with pytest.raises(SystemExit, match="DEMO_USERNAME"):
        await seed_demo_profile(
            expected_username="other",
            repository=AsyncMock(),
            object_storage=MagicMock(),
            cv_text_extraction_agent=AsyncMock(),
            temp_dir=tmp_path,
        )


@pytest.mark.asyncio
async def test_seed_demo_profile_uploads_pdf_and_stores_matching_cv_hash(tmp_path: Path):
    """The extracted artifact hash is the SHA-256 of the PDF that was uploaded."""
    repository = AsyncMock()
    repository.get_cv_text_artifact.return_value = None
    storage = MagicMock()
    agent = AsyncMock()
    agent.extract.return_value = "# Demo CV"

    profile = await seed_demo_profile(
        expected_username="demo",
        repository=repository,
        object_storage=storage,
        cv_text_extraction_agent=agent,
        temp_dir=tmp_path,
    )

    assert profile.username == "demo"
    storage.upload_user_cv.assert_called_once()
    uploaded_path = storage.upload_user_cv.call_args.args[1]
    cv_bytes = Path(uploaded_path).read_bytes()
    repository.upsert_user_profile.assert_awaited_once()
    stored = repository.store_cv_text_artifact.await_args.args[1]
    assert stored == CVTextArtifact(
        cv_text="# Demo CV",
        source_sha256=hashlib.sha256(cv_bytes).hexdigest(),
    )
