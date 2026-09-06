"""Pure routing helpers for the pair subgraph."""

from typing import Literal

from orchestration.state import PairState


def route_after_screen(state: PairState) -> Literal["assess", "pair_end"]:
    """Determine next graph node after screening based on worth_full_assessment flag."""
    if state["skipped_reason"]:
        return "pair_end"
    if state["screening"].get("worth_full_assessment"):
        return "assess"
    return "pair_end"


def route_after_assess(
    state: PairState,
    *,
    min_cv_score: float,
) -> Literal["cover_letter", "pair_end"]:
    """Determine next graph node after assessment based on ATS score threshold."""
    if state["skipped_reason"]:
        return "pair_end"
    assessment = state["assessment"] or {}
    score = assessment.get("cv_ats_match_score")
    if score is not None and score >= min_cv_score:
        return "cover_letter"
    return "pair_end"
