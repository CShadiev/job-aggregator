"""Tests verifying that concurrent pair subgraphs emit only PairOutput without cycle_id collision."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import RunnableConfig

from models.collection_service import CollectionResult
from models.deduplication import NormalizationResult
from models.screening import ScreeningResult
from models.users import CVTextArtifact
from orchestration.graph import build_pipeline_graph
from orchestration.state import new_pipeline_state
from tests.helpers.job_posting import make_job_posting
from tests.unit.test_build_pairs_gating import _profile


@pytest.mark.asyncio
async def test_concurrent_pairs_do_not_collide_on_cycle_id():
    """Multiple concurrent pair subgraphs must not raise InvalidUpdateError on cycle_id."""
    deps = MagicMock()
    deps.repository = AsyncMock()
    deps.object_storage = MagicMock()
    deps.object_storage.get_user_cv.return_value = b"%PDF-test-bytes"
    deps.cv_text_extraction_agent = AsyncMock()
    deps.collection_service = AsyncMock()
    deps.search_service = AsyncMock()
    deps.embedding_client = AsyncMock()
    deps.screening_agent = AsyncMock()
    deps.fit_assessment_agent = AsyncMock()
    deps.cover_letter_agent = AsyncMock()
    deps.screening_model = "test-model"
    deps.thread_id = "test-thread"
    deps.cover_letter_min_cv_score = 80.0
    deps.pair_mode = "cartesian"
    deps.retrieval_ratio = 1.0
    deps.retrieval_min_k = 1
    deps.retrieval_max_k = 100
    deps.demo_username = None

    deps.repository.get_screening.return_value = None
    deps.screening_agent.screen.return_value = ScreeningResult(
        worth_full_assessment=False,
        confidence=0.9,
    )
    deps.repository.store_screening = AsyncMock()

    postings = [
        make_job_posting(uid="j1", title="Dev 1"),
        make_job_posting(uid="j2", title="Dev 2"),
        make_job_posting(uid="j3", title="Dev 3"),
    ]
    deps.collection_service.collect.return_value = CollectionResult(
        postings=postings,
        invalid_entries=[],
        source_checkpoints={},
    )
    deps.collection_service.normalize.return_value = NormalizationResult(
        processed=postings,
        failed=[],
    )
    deps.collection_service.deduplicate.return_value = postings
    deps.repository.upsert_jobs.return_value = None
    deps.embedding_client.embed_texts.return_value = [[0.1] * 8 for _ in postings]
    deps.repository.get_recent_failed_tasks.return_value = []

    deps.repository.get_user_profiles.return_value = [_profile("ada"), _profile("bob")]

    sha = hashlib.sha256(b"%PDF-test-bytes").hexdigest()
    deps.cv_text_extraction_agent.extract.return_value = "# CV Text"
    deps.repository.get_cv_text_artifact.return_value = CVTextArtifact(
        cv_text="# CV Text",
        source_sha256=sha,
    )

    checkpointer = MemorySaver()
    graph = build_pipeline_graph(deps, checkpointer)

    cycle_id = "test-cycle-uuid-1234"
    config: RunnableConfig = {
        "configurable": {"thread_id": "test-thread"},
        "max_concurrency": 10,
    }

    result = await graph.ainvoke(new_pipeline_state(cycle_id=cycle_id), config=config)
    assert result is not None
    assert result.get("collected") == []
    assert result.get("unique_jobs") == []
