"""Tests that pair nodes consume PairState.cv_text and do not re-fetch the CV."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.errors import NodeError
from langgraph.types import Command

from models.failed_tasks import FailedTask
from models.fit_assessment import FitAssessment
from models.screening import ScreeningResult
from orchestration.nodes.pair import make_pair_nodes
from orchestration.state import new_pair_state
from tests.helpers.job_posting import make_job_posting


def _deps() -> MagicMock:
    """Build mocked pipeline deps for pair-node tests."""
    deps = MagicMock()
    deps.repository = AsyncMock()
    deps.repository.get_screening.return_value = None
    deps.repository.get_assessment.return_value = None
    deps.repository.get_user_profile.return_value = MagicMock()
    deps.object_storage = MagicMock()
    deps.screening_agent = AsyncMock()
    deps.screening_agent.screen.return_value = ScreeningResult(
        worth_full_assessment=True,
        confidence=0.9,
    )
    deps.fit_assessment_agent = AsyncMock()
    deps.fit_assessment_agent.assess.return_value = FitAssessment(
        cv_ats_match_score=85.0,
        profile_ats_match_score=80.0,
        summary="Strong fit",
    )
    deps.screening_model = "test-model"
    deps.thread_id = "t1"
    deps.cover_letter_min_cv_score = 80
    return deps


@pytest.mark.asyncio
async def test_screen_passes_pair_state_cv_text_and_skips_s3():
    """Verify screen() uses the precomputed CV text rather than downloading the PDF."""
    deps = _deps()
    posting = make_job_posting(uid="job_cv_1")
    nodes = make_pair_nodes(deps)
    await nodes["screen"](
        new_pair_state(
            cycle_id="c1",
            username="ada",
            cv_text="# Ada CV",
            job=posting.model_dump(mode="json"),
        )
    )
    deps.screening_agent.screen.assert_awaited_once()
    kwargs = deps.screening_agent.screen.await_args.kwargs
    assert kwargs["cv_text"] == "# Ada CV"
    deps.object_storage.get_user_cv.assert_not_called()


@pytest.mark.asyncio
async def test_assess_passes_pair_state_cv_text_and_skips_s3():
    """Verify assess() uses the same CV text and does not re-fetch from object storage."""
    deps = _deps()
    posting = make_job_posting(uid="job_cv_2")
    nodes = make_pair_nodes(deps)
    await nodes["assess"](
        new_pair_state(
            cycle_id="c1",
            username="ada",
            cv_text="# Ada CV",
            job=posting.model_dump(mode="json"),
        )
    )
    deps.fit_assessment_agent.assess.assert_awaited_once()
    kwargs = deps.fit_assessment_agent.assess.await_args.kwargs
    assert kwargs["cv_text"] == "# Ada CV"
    deps.object_storage.get_user_cv.assert_not_called()


@pytest.mark.asyncio
async def test_screen_propagates_errors_so_the_graph_can_retry():
    """Screening must raise so the node retry policy sees the failure."""
    deps = _deps()
    deps.screening_agent.screen.side_effect = RuntimeError("llm down")
    posting = make_job_posting(uid="job_fail")
    nodes = make_pair_nodes(deps)

    with pytest.raises(RuntimeError, match="llm down"):
        await nodes["screen"](
            new_pair_state(
                cycle_id="c1",
                username="ada",
                cv_text="# Ada CV",
                job=posting.model_dump(mode="json"),
            )
        )

    deps.repository.store_failed_task.assert_not_called()


@pytest.mark.asyncio
async def test_screen_failure_handler_records_task_after_retries():
    """The graph error handler persists the pair only once retries are exhausted."""
    deps = _deps()
    posting = make_job_posting(uid="job_fail")
    nodes = make_pair_nodes(deps)
    state = new_pair_state(
        cycle_id="c1",
        username="ada",
        cv_text="# Ada CV",
        job=posting.model_dump(mode="json"),
    )

    command = await nodes["handle_screen_failure"](
        state,
        NodeError(node="screen", error=RuntimeError("llm down")),
    )

    assert isinstance(command, Command)
    assert command.goto == "emit_pair_result"
    assert command.update == {"skipped_reason": "screen_error: llm down"}
    task = deps.repository.store_failed_task.await_args.args[0]
    assert isinstance(task, FailedTask)
    assert task.node == "screen"
    assert task.thread_id == "t1"
    assert task.cycle_id == "c1"
    assert task.error == "llm down"
    assert task.payload == {"username": "ada", "job_uid": "job_fail"}


@pytest.mark.asyncio
async def test_screen_is_retried_and_discarded_only_after_max_attempts():
    """The retry policy re-invokes screening; the failed task is written once attempts run out."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import RetryPolicy

    from orchestration.state import PairState

    deps = _deps()
    deps.screening_agent.screen.side_effect = RuntimeError("llm down")
    posting = make_job_posting(uid="job_fail")
    nodes = make_pair_nodes(deps)
    builder = StateGraph(PairState)
    builder.add_node(
        "screen",
        nodes["screen"],
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_interval=0.01,
            backoff_factor=1,
            max_interval=0.01,
            jitter=False,
            retry_on=(Exception,),
        ),
        error_handler=nodes["handle_screen_failure"],
    )
    builder.add_node("assess", nodes["assess"])
    builder.add_node("emit_pair_result", nodes["emit_pair_result"])
    builder.add_edge(START, "screen")
    builder.add_conditional_edges(
        "screen",
        nodes["route_screen"],
        {"assess": "assess", "pair_end": "emit_pair_result"},
    )
    builder.add_edge("emit_pair_result", END)
    graph = builder.compile()

    result = await graph.ainvoke(
        new_pair_state(
            cycle_id="c1",
            username="ada",
            cv_text="# Ada CV",
            job=posting.model_dump(mode="json"),
        )
    )

    assert deps.screening_agent.screen.await_count == 3
    deps.repository.store_failed_task.assert_awaited_once()
    assert result["skipped_reason"] == "screen_error: llm down"
    assert result["pair_results"] == [
        {
            "username": "ada",
            "job_uid": "job_fail",
            "worth_full_assessment": None,
            "cover_letter_key": None,
            "skipped_reason": "screen_error: llm down",
        }
    ]
