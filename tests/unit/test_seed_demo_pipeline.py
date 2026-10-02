"""Tests for the demo pipeline seed: recent jobs, one profile, no collect."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from job_submit_service import MANUAL_JOB_SOURCE
from models.users import CVTextArtifact
from scripts.seed_demo_pipeline import run_demo_pipeline
from tests.datasets.cover_letter_sample import make_sample_user_profile
from tests.helpers.job_posting import make_job_posting


def _client_error() -> ClientError:
    """S3 error raised when the candidate has no uploaded CV."""
    return ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
        "GetObject",
    )


def _deps() -> MagicMock:
    """Pipeline deps with repository, storage, and retrieval clients mocked."""
    deps = MagicMock()
    deps.repository = AsyncMock()
    deps.object_storage = MagicMock()
    deps.object_storage.get_user_cv.return_value = b"%PDF"
    deps.cv_text_extraction_agent = AsyncMock()
    deps.embedding_client = AsyncMock()
    deps.search_service = AsyncMock()
    deps.collection_service = AsyncMock()
    deps.retrieval_ratio = 0.5
    deps.retrieval_min_k = 1
    deps.retrieval_max_k = 200
    return deps


@pytest.mark.asyncio
async def test_run_demo_pipeline_loads_recent_non_manual_jobs_and_invokes_pairs(monkeypatch):
    """The seed queries Mongo, retrieves for the demo user only, and does not collect."""
    deps = _deps()
    profile = make_sample_user_profile()
    deps.repository.get_user_profile.return_value = profile
    jobs = [
        make_job_posting(uid="linkedin:1", source="linkedin"),
        make_job_posting(uid="arbeitnow:2", source="arbeitnow"),
    ]
    deps.repository.get_recent_jobs.return_value = jobs
    monkeypatch.setattr(
        "scripts.seed_demo_pipeline.ensure_cv_text",
        AsyncMock(return_value=CVTextArtifact(cv_text="# CV", source_sha256="a" * 64)),
    )
    retrieved = [
        {"username": profile.username, "job_uid": "linkedin:1", "job": jobs[0].model_dump()},
    ]
    retrieve = AsyncMock(return_value=retrieved)
    monkeypatch.setattr("scripts.seed_demo_pipeline.retrieve_topk_pairs", retrieve)
    pair_graph = AsyncMock()
    monkeypatch.setattr(
        "scripts.seed_demo_pipeline.build_pair_subgraph",
        lambda _deps: pair_graph,
    )

    n_pairs = await run_demo_pipeline(limit=100, username="demo", deps=deps, concurrency=2)

    assert n_pairs == 1
    deps.repository.get_recent_jobs.assert_awaited_once_with(
        limit=100, exclude_source=MANUAL_JOB_SOURCE
    )
    deps.repository.get_user_profiles.assert_not_awaited()
    deps.collection_service.collect.assert_not_awaited()
    assert retrieve.await_args is not None
    assert retrieve.await_args.kwargs["profiles"] == [profile]
    assert retrieve.await_args.kwargs["k"] == 1
    pair_graph.ainvoke.assert_awaited_once()
    state = pair_graph.ainvoke.await_args.args[0]
    assert state["username"] == profile.username
    assert state["cv_text"] == "# CV"
    assert state["job"]["uid"] == "linkedin:1"


@pytest.mark.asyncio
async def test_run_demo_pipeline_requires_a_profile():
    """A missing demo profile is an operator error, not an empty successful run."""
    deps = _deps()
    deps.repository.get_user_profile.return_value = None
    with pytest.raises(SystemExit, match="User profile not found"):
        await run_demo_pipeline(limit=100, username="demo", deps=deps, concurrency=1)


@pytest.mark.asyncio
async def test_run_demo_pipeline_requires_a_cv():
    """A missing S3 CV fails before retrieval spend."""
    deps = _deps()
    deps.repository.get_user_profile.return_value = make_sample_user_profile()
    deps.object_storage.get_user_cv.side_effect = _client_error()
    with pytest.raises(SystemExit, match="User CV not found"):
        await run_demo_pipeline(limit=100, username="demo", deps=deps, concurrency=1)


@pytest.mark.asyncio
async def test_run_demo_pipeline_returns_zero_when_mongo_has_no_jobs(monkeypatch):
    """An empty corpus is a no-op, not a collect cycle."""
    deps = _deps()
    deps.repository.get_user_profile.return_value = make_sample_user_profile()
    deps.repository.get_recent_jobs.return_value = []
    retrieve = AsyncMock()
    monkeypatch.setattr("scripts.seed_demo_pipeline.retrieve_topk_pairs", retrieve)

    n_pairs = await run_demo_pipeline(limit=100, username="demo", deps=deps, concurrency=1)

    assert n_pairs == 0
    retrieve.assert_not_awaited()
    deps.collection_service.collect.assert_not_awaited()
