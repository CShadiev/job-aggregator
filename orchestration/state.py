"""Typed graph state for the LangGraph job pipeline."""

import operator
from typing import Annotated, Any, TypedDict


class PipelineState(TypedDict):
    """Parent graph state for one collection → map-reduce cycle."""

    cycle_id: str
    collected: list[dict[str, Any]]
    normalize_failed: list[dict[str, Any]]
    unique_jobs: list[dict[str, Any]]
    pairs: list[dict[str, Any]]
    pair_results: Annotated[list[dict[str, Any]], operator.add]


class PairState(TypedDict):
    """Per-(username, job) subgraph state."""

    cycle_id: str
    username: str
    job: dict[str, Any]
    screening: dict[str, Any]
    assessment: dict[str, Any] | None
    cover_letter_key: str | None
    skipped_reason: str | None
    pair_results: Annotated[list[dict[str, Any]], operator.add]


def new_pipeline_state(
    *,
    cycle_id: str = "",
    collected: list[dict[str, Any]] | None = None,
    normalize_failed: list[dict[str, Any]] | None = None,
    unique_jobs: list[dict[str, Any]] | None = None,
    pairs: list[dict[str, Any]] | None = None,
    pair_results: list[dict[str, Any]] | None = None,
) -> PipelineState:
    """Build a complete ``PipelineState`` with empty defaults for omitted fields."""
    return {
        "cycle_id": cycle_id,
        "collected": collected if collected is not None else [],
        "normalize_failed": normalize_failed if normalize_failed is not None else [],
        "unique_jobs": unique_jobs if unique_jobs is not None else [],
        "pairs": pairs if pairs is not None else [],
        "pair_results": pair_results if pair_results is not None else [],
    }


def new_pair_state(
    *,
    cycle_id: str = "",
    username: str = "",
    job: dict[str, Any] | None = None,
    screening: dict[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
    cover_letter_key: str | None = None,
    skipped_reason: str | None = None,
    pair_results: list[dict[str, Any]] | None = None,
) -> PairState:
    """Build a complete ``PairState`` with empty defaults for omitted fields."""
    return {
        "cycle_id": cycle_id,
        "username": username,
        "job": job if job is not None else {},
        "screening": screening if screening is not None else {},
        "assessment": assessment,
        "cover_letter_key": cover_letter_key,
        "skipped_reason": skipped_reason,
        "pair_results": pair_results if pair_results is not None else [],
    }


def build_pair_list(usernames: list[str], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cartesian product of usernames × jobs for map fan-out."""
    return [
        {"username": username, "job_uid": job["uid"], "job": job}
        for job in jobs
        for username in usernames
    ]


def cleared_batch_state() -> dict[str, Any]:
    """Empty batch-scoped channels so long-lived thread state does not grow."""
    state = new_pipeline_state()
    return {
        "collected": state["collected"],
        "normalize_failed": state["normalize_failed"],
        "unique_jobs": state["unique_jobs"],
        "pairs": state["pairs"],
        "pair_results": state["pair_results"],
    }


def pair_result_summary(state: PairState) -> dict[str, Any]:
    """Compact per-pair summary appended to parent ``pair_results``."""
    job = state["job"]
    screening = state["screening"]
    assessment = state["assessment"]
    summary: dict[str, Any] = {
        "username": state["username"],
        "job_uid": job.get("uid"),
        "worth_full_assessment": screening.get("worth_full_assessment"),
        "cover_letter_key": state["cover_letter_key"],
        "skipped_reason": state["skipped_reason"],
    }
    if assessment:
        summary["cv_ats_match_score"] = assessment.get("cv_ats_match_score")
        summary["profile_ats_match_score"] = assessment.get("profile_ats_match_score")
    return summary
