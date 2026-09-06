"""Unit tests for LangGraph pipeline routing and pure helpers."""

from orchestration.routing import route_after_assess, route_after_screen
from orchestration.state import (
    build_pair_list,
    cleared_batch_state,
    new_pair_state,
    new_pipeline_state,
    pair_result_summary,
)


class TestRouteAfterScreen:
    """Tests for conditional branch routing after screening step."""

    def test_worth_full_assessment_routes_to_assess(self):
        """Verify routing to assess when screening passes."""
        assert (
            route_after_screen(
                new_pair_state(
                    screening={"worth_full_assessment": True, "confidence": 0.9},
                )
            )
            == "assess"
        )

    def test_drop_routes_to_pair_end(self):
        """Verify routing to pair_end when screening fails."""
        assert (
            route_after_screen(
                new_pair_state(
                    screening={"worth_full_assessment": False, "confidence": 0.8},
                )
            )
            == "pair_end"
        )

    def test_skipped_reason_routes_to_pair_end(self):
        """Verify routing to pair_end when error reason is present."""
        assert (
            route_after_screen(
                new_pair_state(
                    skipped_reason="screen_error: boom",
                    screening={"worth_full_assessment": True, "confidence": 0.9},
                )
            )
            == "pair_end"
        )

    def test_missing_screening_routes_to_pair_end(self):
        """Verify routing to pair_end when screening dictionary is empty."""
        assert route_after_screen(new_pair_state()) == "pair_end"


class TestRouteAfterAssess:
    """Tests for conditional branch routing after fit assessment step."""

    def test_score_at_threshold_routes_to_cover_letter(self):
        """Verify routing to cover_letter when score meets threshold exactly."""
        assert (
            route_after_assess(
                new_pair_state(assessment={"cv_ats_match_score": 80}),
                min_cv_score=80,
            )
            == "cover_letter"
        )

    def test_score_above_threshold_routes_to_cover_letter(self):
        """Verify routing to cover_letter when score exceeds threshold."""
        assert (
            route_after_assess(
                new_pair_state(assessment={"cv_ats_match_score": 91.5}),
                min_cv_score=80,
            )
            == "cover_letter"
        )

    def test_score_below_threshold_routes_to_pair_end(self):
        """Verify routing to pair_end when score is below threshold."""
        assert (
            route_after_assess(
                new_pair_state(assessment={"cv_ats_match_score": 79.9}),
                min_cv_score=80,
            )
            == "pair_end"
        )

    def test_skipped_reason_routes_to_pair_end(self):
        """Verify routing to pair_end when skipped reason is present."""
        assert (
            route_after_assess(
                new_pair_state(
                    skipped_reason="assess_error: boom",
                    assessment={"cv_ats_match_score": 95},
                ),
                min_cv_score=80,
            )
            == "pair_end"
        )

    def test_missing_assessment_routes_to_pair_end(self):
        """Verify routing to pair_end when assessment is None."""
        assert route_after_assess(new_pair_state(), min_cv_score=80) == "pair_end"


class TestBuildPairList:
    """Tests for cartesian pair list generation."""

    def test_cartesian_product(self):
        """Verify product generation of (user, job) pairs."""
        jobs = [{"uid": "j1"}, {"uid": "j2"}]
        pairs = build_pair_list(["alice", "bob"], jobs)
        assert pairs == [
            {"username": "alice", "job_uid": "j1", "job": {"uid": "j1"}},
            {"username": "bob", "job_uid": "j1", "job": {"uid": "j1"}},
            {"username": "alice", "job_uid": "j2", "job": {"uid": "j2"}},
            {"username": "bob", "job_uid": "j2", "job": {"uid": "j2"}},
        ]

    def test_empty_jobs_yields_no_pairs(self):
        """Verify empty jobs list yields empty pair list."""
        assert build_pair_list(["alice"], []) == []

    def test_empty_users_yields_no_pairs(self):
        """Verify empty users list yields empty pair list."""
        assert build_pair_list([], [{"uid": "j1"}]) == []


class TestStateFactories:
    """Tests for pipeline state dictionary factories."""

    def test_new_pipeline_state_defaults(self):
        """Verify default state created by new_pipeline_state."""
        state = new_pipeline_state(cycle_id="c1")
        assert state == {
            "cycle_id": "c1",
            "collected": [],
            "normalize_failed": [],
            "unique_jobs": [],
            "pairs": [],
            "pair_results": [],
        }

    def test_new_pair_state_defaults(self):
        """Verify default state created by new_pair_state."""
        state = new_pair_state(username="alice", job={"uid": "j1"})
        assert state == {
            "cycle_id": "",
            "username": "alice",
            "job": {"uid": "j1"},
            "screening": {},
            "assessment": None,
            "cover_letter_key": None,
            "skipped_reason": None,
            "pair_results": [],
        }


class TestClearedBatchState:
    """Tests for cleared_batch_state helper."""

    def test_clears_all_batch_list_channels(self):
        """Verify all list channels are reset to empty lists."""
        cleared = cleared_batch_state()
        assert cleared == {
            "collected": [],
            "normalize_failed": [],
            "unique_jobs": [],
            "pairs": [],
            "pair_results": [],
        }


class TestPairResultSummary:
    """Tests for pair_result_summary aggregation helper."""

    def test_includes_scores_when_assessment_present(self):
        """Verify summary extracts all metrics and S3 key."""
        summary = pair_result_summary(
            new_pair_state(
                username="alice",
                job={"uid": "job-1"},
                screening={"worth_full_assessment": True},
                assessment={
                    "cv_ats_match_score": 88,
                    "profile_ats_match_score": 90,
                },
                cover_letter_key="s3://key",
            )
        )
        assert summary == {
            "username": "alice",
            "job_uid": "job-1",
            "worth_full_assessment": True,
            "cover_letter_key": "s3://key",
            "skipped_reason": None,
            "cv_ats_match_score": 88,
            "profile_ats_match_score": 90,
        }
