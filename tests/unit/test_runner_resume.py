"""Tests verifying Path A crash-resumption logic in orchestration runner."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.runner import run_once


@pytest.mark.asyncio
async def test_run_once_resumes_when_snapshot_has_next():
    """When snapshot has pending tasks, run_once invokes with None and preserves cycle_id."""
    graph = MagicMock()
    snapshot = SimpleNamespace(
        next=("screen",),
        values={"cycle_id": "preserved-cycle-id-123"},
    )
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.ainvoke = AsyncMock()

    config = MagicMock()
    config.PIPELINE_THREAD_ID = "job-pipeline"
    config.PIPELINE_PAIR_CONCURRENCY = 10

    await run_once(graph=graph, config=config)

    expected_config = {
        "configurable": {"thread_id": "job-pipeline"},
        "max_concurrency": 10,
    }
    graph.ainvoke.assert_awaited_once_with(None, config=expected_config)


@pytest.mark.asyncio
async def test_run_once_starts_fresh_when_snapshot_next_is_empty():
    """When snapshot has no pending tasks, run_once invokes with fresh state."""
    graph = MagicMock()
    snapshot = SimpleNamespace(
        next=(),
        values={"cycle_id": "old-cycle-id"},
    )
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.ainvoke = AsyncMock()

    config = MagicMock()
    config.PIPELINE_THREAD_ID = "job-pipeline"
    config.PIPELINE_PAIR_CONCURRENCY = 10

    await run_once(graph=graph, config=config)

    graph.ainvoke.assert_awaited_once()
    args, kwargs = graph.ainvoke.await_args
    state = args[0]
    assert isinstance(state, dict)
    assert state["cycle_id"] != "old-cycle-id"
    assert len(state["cycle_id"]) > 0
    assert kwargs["config"]["configurable"]["thread_id"] == "job-pipeline"
