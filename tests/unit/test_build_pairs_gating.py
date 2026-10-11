"""Unit tests for pair-building gating and embedding nodes in batch orchestration."""

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.failed_tasks import FailedTask, NodeName
from models.users import (
    CareerGoals,
    Contact,
    CVTextArtifact,
    Experience,
    IndustryPreferences,
    LocationPreferences,
    Profile,
    RoleFitSignals,
    Summary,
    TechnicalSkills,
    UserProfile,
)
from orchestration.nodes.batch import FAILED_JOB_MAX_AGE, FAILED_JOB_NODES, make_batch_nodes
from orchestration.state import new_pipeline_state
from search.models import SearchHit, SearchHits
from tests.helpers.job_posting import make_job_posting


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


def _deps(
    *,
    pair_mode: str = "topk",
    retrieval_ratio: float = 0.5,
    retrieval_min_k: int = 1,
    retrieval_max_k: int = 200,
):
    """Build mock PipelineDependencies for testing batch nodes."""
    deps = MagicMock()
    deps.repository = AsyncMock()
    cv_bytes = b"%PDF-test"
    deps.object_storage = MagicMock()
    deps.object_storage.get_user_cv.return_value = cv_bytes
    deps.cv_text_extraction_agent = AsyncMock()
    deps.repository.get_cv_text_artifact.return_value = CVTextArtifact(
        cv_text="# Ada CV",
        source_sha256=hashlib.sha256(cv_bytes).hexdigest(),
    )
    deps.collection_service = AsyncMock()
    deps.thread_id = "t1"
    deps.search_service = AsyncMock()
    deps.embedding_client = AsyncMock()
    deps.embedding_client.embed_profile.return_value = [0.1] * 8
    deps.pair_mode = pair_mode
    deps.retrieval_ratio = retrieval_ratio
    deps.retrieval_min_k = retrieval_min_k
    deps.retrieval_max_k = retrieval_max_k
    deps.demo_username = None
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
    assert all(pair["cv_text"] == "# Ada CV" for pair in result["pairs"])
    deps.search_service.search_jobs.assert_not_called()


@pytest.mark.asyncio
async def test_topk_caps_pairs_at_users_times_k():
    """Verify that topk mode limits pairs to top K search results per user."""
    deps = _deps(pair_mode="topk", retrieval_ratio=0.4)
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
async def test_build_pairs_regenerates_cv_text_when_pdf_digest_changes():
    """Verify a replaced CV invalidates the persisted rendering during pair build."""
    deps = _deps(pair_mode="cartesian")
    deps.repository.get_user_profiles.return_value = [_profile("ada")]
    deps.repository.get_cv_text_artifact.return_value = CVTextArtifact(
        cv_text="# Stale CV",
        source_sha256="0" * 64,
    )
    deps.cv_text_extraction_agent.extract.return_value = "# Fresh CV"
    nodes = make_batch_nodes(deps)
    result = await nodes["build_pairs"](
        new_pipeline_state(cycle_id="c1", unique_jobs=[{"uid": "j1", "title": "A"}])
    )
    assert result["pairs"][0]["cv_text"] == "# Fresh CV"
    deps.cv_text_extraction_agent.extract.assert_awaited_once()
    deps.object_storage.get_user_cv.assert_called_once_with("ada")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ratio", "n_jobs", "min_k", "max_k", "expected_k"),
    [
        (0.5, 10, 1, 200, 5),
        (0.5, 5, 1, 200, 3),
        (1.0, 4, 1, 200, 4),
        (0.01, 3, 1, 200, 1),
        (0.5, 1000, 1, 200, 200),
        (0.5, 20, 15, 200, 15),
        (0.5, 20, 15, 12, 12),
    ],
)
async def test_topk_size_scales_with_batch_share(
    ratio: float, n_jobs: int, min_k: int, max_k: int, expected_k: int
):
    """Verify the retrieval cutoff is a share of the batch, rounded up and clamped to bounds."""
    deps = _deps(
        pair_mode="topk",
        retrieval_ratio=ratio,
        retrieval_min_k=min_k,
        retrieval_max_k=max_k,
    )
    deps.repository.get_user_profiles.return_value = [_profile("ada")]
    deps.search_service.search_jobs.return_value = SearchHits(hits=[])
    nodes = make_batch_nodes(deps)
    jobs = [{"uid": f"j{i}"} for i in range(n_jobs)]
    await nodes["build_pairs"](new_pipeline_state(cycle_id="c1", unique_jobs=jobs))
    assert deps.search_service.search_jobs.await_args.kwargs["size"] == expected_k


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


def _failed_task(node: NodeName, job_uid: str | None) -> FailedTask:
    """Build a failed-task envelope for requeue tests."""
    payload = {"username": "ada"}
    if job_uid is not None:
        payload["job_uid"] = job_uid
    return FailedTask(
        node=node,
        thread_id="old",
        cycle_id="old-cycle",
        error="llm down",
        payload=payload,
    )


def test_pipeline_requeues_failed_jobs_between_embed_and_pairs():
    """The batch spine inserts the requeue node after embedding and before pairing."""
    from langgraph.checkpoint.memory import MemorySaver

    from orchestration.graph import build_pair_subgraph, build_pipeline_graph

    pair = build_pair_subgraph(MagicMock())
    assert "__error_handler__screen" in pair.nodes

    pipeline = build_pipeline_graph(MagicMock(), MemorySaver())
    edges = {(edge.source, edge.target) for edge in pipeline.get_graph().edges}
    assert ("embed_jobs", "requeue_failed_jobs") in edges
    assert ("requeue_failed_jobs", "build_pairs") in edges


@pytest.mark.asyncio
async def test_requeue_failed_jobs_appends_recent_failures():
    """Jobs that failed within 72 hours are added to unique_jobs before pairing."""
    deps = _deps()
    fresh = make_job_posting(uid="fresh")
    failed = make_job_posting(uid="failed")
    deps.repository.get_recent_failed_tasks.return_value = [
        _failed_task("screen", "fresh"),
        _failed_task("screen", "failed"),
        _failed_task("assess", "failed"),
        _failed_task("cover_letter", "gone"),
        _failed_task("screen", None),
    ]
    deps.repository.get_jobs_by_uids.return_value = [failed]
    nodes = make_batch_nodes(deps)

    result = await nodes["requeue_failed_jobs"](
        new_pipeline_state(
            cycle_id="c1",
            unique_jobs=[fresh.model_dump(mode="json")],
        )
    )

    assert [job["uid"] for job in result["unique_jobs"]] == ["fresh", "failed"]
    deps.repository.get_jobs_by_uids.assert_awaited_once_with(["failed", "gone"])
    kwargs = deps.repository.get_recent_failed_tasks.await_args.kwargs
    assert kwargs["nodes"] == FAILED_JOB_NODES
    age = datetime.now(UTC) - kwargs["since"]
    assert (
        FAILED_JOB_MAX_AGE - timedelta(seconds=5)
        <= age
        <= FAILED_JOB_MAX_AGE + timedelta(seconds=5)
    )


@pytest.mark.asyncio
async def test_requeue_failed_jobs_leaves_batch_unchanged_when_nothing_failed():
    """An empty failure window does not rewrite unique_jobs."""
    deps = _deps()
    deps.repository.get_recent_failed_tasks.return_value = []
    nodes = make_batch_nodes(deps)

    result = await nodes["requeue_failed_jobs"](
        new_pipeline_state(cycle_id="c1", unique_jobs=[{"uid": "fresh"}])
    )

    assert result == {}
    deps.repository.get_jobs_by_uids.assert_not_called()


@pytest.mark.asyncio
async def test_requeue_failed_jobs_records_task_and_reraises():
    """A lookup failure aborts the cycle after it is recorded."""
    deps = _deps()
    deps.repository.get_recent_failed_tasks.side_effect = RuntimeError("mongo down")
    nodes = make_batch_nodes(deps)

    with pytest.raises(RuntimeError, match="mongo down"):
        await nodes["requeue_failed_jobs"](
            new_pipeline_state(cycle_id="c1", unique_jobs=[{"uid": "fresh"}])
        )

    task = deps.repository.store_failed_task.await_args.args[0]
    assert isinstance(task, FailedTask)
    assert task.node == "requeue_failed_jobs"
    assert task.error == "mongo down"


@pytest.mark.asyncio
async def test_build_pairs_skips_configured_demo_user():
    """The scheduled worker must not retrieve or extract CV text for the demo account."""
    deps = _deps(pair_mode="topk", retrieval_ratio=0.5)
    deps.demo_username = "demo"
    deps.repository.get_user_profiles.return_value = [_profile("ada"), _profile("demo")]
    deps.search_service.search_jobs.return_value = SearchHits(hits=[SearchHit(uid="j1", score=1.0)])
    nodes = make_batch_nodes(deps)
    jobs = [{"uid": "j1", "title": "A"}, {"uid": "j2", "title": "B"}]
    result = await nodes["build_pairs"](new_pipeline_state(cycle_id="c1", unique_jobs=jobs))

    assert {pair["username"] for pair in result["pairs"]} == {"ada"}
    deps.object_storage.get_user_cv.assert_called_once_with("ada")
    assert deps.search_service.search_jobs.await_count == 1
    assert deps.embedding_client.embed_profile.await_args.args[0].username == "ada"


@pytest.mark.asyncio
async def test_build_pairs_includes_demo_when_username_unset():
    """With demo hosting off, every profile is paired as before."""
    deps = _deps(pair_mode="cartesian")
    deps.demo_username = None
    deps.repository.get_user_profiles.return_value = [_profile("ada"), _profile("demo")]
    nodes = make_batch_nodes(deps)
    jobs = [{"uid": "j1", "title": "A"}]
    result = await nodes["build_pairs"](new_pipeline_state(cycle_id="c1", unique_jobs=jobs))
    assert {pair["username"] for pair in result["pairs"]} == {"ada", "demo"}
