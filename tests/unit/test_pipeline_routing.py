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
    def test_worth_full_assessment_routes_to_assess(self):
        assert route_after_screen(new_pair_state(
            screening={"worth_full_assessment": True, "confidence": 0.9},
        )) == "assess"

    def test_drop_routes_to_pair_end(self):
        assert route_after_screen(new_pair_state(
            screening={"worth_full_assessment": False, "confidence": 0.8},
        )) == "pair_end"

    def test_skipped_reason_routes_to_pair_end(self):
        assert route_after_screen(new_pair_state(
            skipped_reason="screen_error: boom",
            screening={"worth_full_assessment": True, "confidence": 0.9},
        )) == "pair_end"

    def test_missing_screening_routes_to_pair_end(self):
        assert route_after_screen(new_pair_state()) == "pair_end"


class TestRouteAfterAssess:
    def test_score_at_threshold_routes_to_cover_letter(self):
        assert route_after_assess(
            new_pair_state(assessment={"cv_ats_match_score": 80}),
            min_cv_score=80,
        ) == "cover_letter"

    def test_score_above_threshold_routes_to_cover_letter(self):
        assert route_after_assess(
            new_pair_state(assessment={"cv_ats_match_score": 91.5}),
            min_cv_score=80,
        ) == "cover_letter"

    def test_score_below_threshold_routes_to_pair_end(self):
        assert route_after_assess(
            new_pair_state(assessment={"cv_ats_match_score": 79.9}),
            min_cv_score=80,
        ) == "pair_end"

    def test_skipped_reason_routes_to_pair_end(self):
        assert route_after_assess(
            new_pair_state(
                skipped_reason="assess_error: boom",
                assessment={"cv_ats_match_score": 95},
            ),
            min_cv_score=80,
        ) == "pair_end"

    def test_missing_assessment_routes_to_pair_end(self):
        assert route_after_assess(new_pair_state(), min_cv_score=80) == "pair_end"


class TestBuildPairList:
    def test_cartesian_product(self):
        jobs = [{"uid": "j1"}, {"uid": "j2"}]
        pairs = build_pair_list(["alice", "bob"], jobs)
        assert pairs == [
            {"username": "alice", "job_uid": "j1", "job": {"uid": "j1"}},
            {"username": "bob", "job_uid": "j1", "job": {"uid": "j1"}},
            {"username": "alice", "job_uid": "j2", "job": {"uid": "j2"}},
            {"username": "bob", "job_uid": "j2", "job": {"uid": "j2"}},
        ]

    def test_empty_jobs_yields_no_pairs(self):
        assert build_pair_list(["alice"], []) == []

    def test_empty_users_yields_no_pairs(self):
        assert build_pair_list([], [{"uid": "j1"}]) == []


class TestStateFactories:
    def test_new_pipeline_state_defaults(self):
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
    def test_clears_all_batch_list_channels(self):
        cleared = cleared_batch_state()
        assert cleared == {
            "collected": [],
            "normalize_failed": [],
            "unique_jobs": [],
            "pairs": [],
            "pair_results": [],
        }


class TestPairResultSummary:
    def test_includes_scores_when_assessment_present(self):
        summary = pair_result_summary(new_pair_state(
            username="alice",
            job={"uid": "job-1"},
            screening={"worth_full_assessment": True},
            assessment={
                "cv_ats_match_score": 88,
                "profile_ats_match_score": 90,
            },
            cover_letter_key="s3://key",
        ))
        assert summary == {
            "username": "alice",
            "job_uid": "job-1",
            "worth_full_assessment": True,
            "cover_letter_key": "s3://key",
            "skipped_reason": None,
            "cv_ats_match_score": 88,
            "profile_ats_match_score": 90,
        }
