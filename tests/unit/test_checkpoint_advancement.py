"""Tests verifying that collector checkpoints are deferred to finalize and not updated prematurely."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from collection_service.collection_service import CollectionService
from models.collection_service import CollectionResult
from orchestration.nodes.batch import make_batch_nodes
from orchestration.state import new_pipeline_state
from tests.helpers.job_posting import make_job_posting


@pytest.mark.asyncio
async def test_collection_service_stages_checkpoint_without_calling_repo():
    """CollectionService.collect() must not call set_checkpoint on repository."""
    repo = AsyncMock()
    repo.get_checkpoint.return_value = None
    agent = AsyncMock()

    collector = MagicMock()
    collector.get_source_name.return_value = "source_a"
    posted_at = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    posting = make_job_posting(uid="s1", source="source_a", posted_at=posted_at)
    collector.collect_jobs = AsyncMock(
        return_value=CollectionResult(postings=[posting], invalid_entries=[])
    )

    service = CollectionService(repo=repo, agent=agent, collectors=[collector])
    result = await service.collect()

    repo.set_checkpoint.assert_not_called()
    assert result.source_checkpoints == {"source_a": posted_at}


@pytest.mark.asyncio
async def test_batch_nodes_defer_checkpoint_to_finalize():
    """Collect node stages source_checkpoints in state; finalize commits them to repository."""
    deps = MagicMock()
    deps.repository = AsyncMock()
    deps.collection_service = AsyncMock()
    deps.thread_id = "test-thread"

    posted_at = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    posting = make_job_posting(uid="s1", source="source_a", posted_at=posted_at)

    deps.collection_service.collect.return_value = CollectionResult(
        postings=[posting],
        invalid_entries=[],
        source_checkpoints={"source_a": posted_at},
    )

    nodes = make_batch_nodes(deps)

    collect_state = await nodes["collect"](new_pipeline_state(cycle_id="c1"))
    deps.repository.set_checkpoint.assert_not_called()
    assert collect_state["source_checkpoints"] == {"source_a": posted_at.isoformat()}

    pipeline_state = new_pipeline_state(
        cycle_id="c1",
        source_checkpoints=collect_state["source_checkpoints"],
        pair_results=[],
    )
    await nodes["finalize"](pipeline_state)
    deps.repository.set_checkpoint.assert_awaited_once_with("source_a", posted_at)
