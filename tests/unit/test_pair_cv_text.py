"""Tests that pair nodes consume PairState.cv_text and do not re-fetch the CV."""

from unittest.mock import AsyncMock, MagicMock

import pytest

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
