"""Unit tests for pair-building gating and embedding nodes in batch orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from models.failed_tasks import FailedTask
from models.users import (
    CareerGoals,
    Contact,
    Experience,
    IndustryPreferences,
    LocationPreferences,
    Profile,
    RoleFitSignals,
    Summary,
    TechnicalSkills,
    UserProfile,
)
from orchestration.nodes.batch import make_batch_nodes
from orchestration.state import new_pipeline_state
from search.models import SearchHit, SearchHits


def _profile(username: str = "ada") -> UserProfile:
    """Create a minimal UserProfile for testing."""
    return UserProfile(
        profile=Profile(
            name=username,
            title="Engineer",
            location="Berlin",
            contact=Contact(email=f"{username}@example.com"),
        ),
        summary=Summary(headline="Backend", description="Python APIs"),
        keyDifferentiators=[],
        certifications=[],
        technicalSkills=TechnicalSkills(),
        coreCompetencies=[],
        experience=[
            Experience(
                title="Engineer",
                company="Acme",
                startDate="2020",
                endDate="2024",
                responsibilities=["Built APIs"],
            )
        ],
        education=[],
        careerGoals=CareerGoals(
            targetRoles=["Backend"],
            avoidRoles=[],
            locationPreferences=LocationPreferences(
                primary="Berlin", remote="yes", relocation="no"
            ),
            industryPreferences=IndustryPreferences(strongInterest=[], lessInterested=[]),
            values=[],
            seekingInRole=[],
        ),
        workAuthorization=[],
        roleFitSignals=RoleFitSignals(strongFit=[], moderateFit=[], weakFit=[]),
        languages=[],
        username=username,
    )


def _deps(*, pair_mode: str = "topk", retrieval_k: int = 2):
    """Build mock PipelineDependencies for testing batch nodes."""
    deps = MagicMock()
    deps.repository = AsyncMock()
    deps.collection_service = AsyncMock()
    deps.thread_id = "t1"
    deps.search_service = AsyncMock()
    deps.embedding_client = AsyncMock()
    deps.embedding_client.embed_profile.return_value = [0.1] * 8
    deps.pair_mode = pair_mode
    deps.retrieval_k = retrieval_k
    return deps


@pytest.mark.asyncio
async def test_cartesian_mode_uses_full_product():
    """Verify that cartesian mode creates user x job pair combinations without search."""
    deps = _deps(pair_mode="cartesian")
    deps.repository.get_user_profiles.return_value = [_profile("ada"), _profile("bob")]
    nodes = make_batch_nodes(deps)
    jobs = [{"uid": "j1", "title": "A"}, {"uid": "j2", "title": "B"}]
    result = await nodes["build_pairs"](new_pipeline_state(cycle_id="c1", unique_jobs=jobs))
    assert len(result["pairs"]) == 4
    deps.search_service.search_jobs.assert_not_called()


@pytest.mark.asyncio
async def test_topk_caps_pairs_at_users_times_k():
    """Verify that topk mode limits pairs to top K search results per user."""
    deps = _deps(pair_mode="topk", retrieval_k=2)
    deps.repository.get_user_profiles.return_value = [_profile("ada"), _profile("bob")]
    deps.search_service.search_jobs.return_value = SearchHits(
        hits=[SearchHit(uid="j1", score=1.0), SearchHit(uid="j2", score=0.5)]
    )
    nodes = make_batch_nodes(deps)
    jobs = [{"uid": f"j{i}"} for i in range(1, 6)]
    result = await nodes["build_pairs"](new_pipeline_state(cycle_id="c1", unique_jobs=jobs))
    assert len(result["pairs"]) <= 2 * 2
    assert {pair["username"] for pair in result["pairs"]} == {"ada", "bob"}
    assert all(pair["job"]["uid"] in {"j1", "j2"} for pair in result["pairs"])


@pytest.mark.asyncio
async def test_build_pairs_hard_fails_and_records_task():
    """Verify that build_pairs records a failed task upon search errors."""
    deps = _deps(pair_mode="topk")
    deps.repository.get_user_profiles.return_value = [_profile()]
    deps.search_service.search_jobs.side_effect = RuntimeError("opensearch down")
    nodes = make_batch_nodes(deps)
    with pytest.raises(RuntimeError, match="opensearch down"):
        await nodes["build_pairs"](new_pipeline_state(cycle_id="c1", unique_jobs=[{"uid": "j1"}]))
    task = deps.repository.store_failed_task.await_args.args[0]
    assert isinstance(task, FailedTask)
    assert task.node == "build_pairs"


@pytest.mark.asyncio
async def test_embed_jobs_hard_fails_and_records_task():
    """Verify that embed_jobs records a failed task on embedding client errors."""
    deps = _deps()
    deps.embedding_client.embed_texts.side_effect = RuntimeError("openai down")
    nodes = make_batch_nodes(deps)
    job = {
        "uid": "src:1",
        "source": "src",
        "title": "Engineer",
        "company": "Acme",
        "location": "Berlin",
        "remote": True,
        "url": "https://example.com/1",
        "description_raw": "Python",
        "posted_at": "2026-01-01T00:00:00Z",
        "collected_at": "2026-01-01T00:00:00Z",
    }
    with pytest.raises(RuntimeError, match="openai down"):
        await nodes["embed_jobs"](new_pipeline_state(cycle_id="c1", unique_jobs=[job]))
    task = deps.repository.store_failed_task.await_args.args[0]
    assert task.node == "embed_jobs"
