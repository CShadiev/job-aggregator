"""Ranking and gating metrics for the retrieval benchmark. Pure functions, no I/O."""

from __future__ import annotations

import math


def _require_non_negative_k(k: int) -> None:
    """Validate that ranking depth k is a positive integer."""
    if k < 1:
        raise ValueError("k must be >= 1")


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant documents appearing in the top-``k`` retrieved."""
    _require_non_negative_k(k)
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def fitting_recall_at_k(retrieved: list[str], fitting_uids: set[str], k: int) -> float:
    """Fraction of fitting jobs (worth_full_assessment=True) captured in top-``k``."""
    return recall_at_k(retrieved, fitting_uids, k)


def good_recall_at_k(retrieved: list[str], good_uids: set[str], k: int) -> float:
    """Fraction of top-tier 'good' jobs captured in top-``k``."""
    return recall_at_k(retrieved, good_uids, k)


def moderate_recall_at_k(retrieved: list[str], moderate_uids: set[str], k: int) -> float:
    """Fraction of 'moderate' fit jobs captured in top-``k``."""
    return recall_at_k(retrieved, moderate_uids, k)


def naive_recall_at_k(k: int, n_total: int) -> float:
    """Expected recall of any positive class if a sample of ``k`` items is drawn uniformly at random without replacement.

    For a corpus of size ``N`` and positive set of size ``R``, the expected count of positive items
    in a random sample of size ``k`` is ``k * (R / N)``, yielding expected recall
    ``(k * R / N) / R = min(1.0, k / N)``.
    """
    _require_non_negative_k(k)
    if n_total <= 0:
        return 0.0
    return min(1.0, float(k) / float(n_total))


def gating_reduction_rate(k: int, n_total: int) -> float:
    """Fraction of corpus jobs eliminated from downstream assessment at cutoff ``k``."""
    if n_total <= 0:
        return 0.0
    return max(0.0, float(n_total - min(k, n_total)) / n_total)


def llm_calls_saved(k: int, n_total: int) -> int:
    """Number of downstream LLM assessments avoided at cutoff ``k``."""
    return max(0, n_total - k)


def _dcg(gains: list[float]) -> float:
    """Compute Discounted Cumulative Gain for an ordered list of relevance gains."""
    return sum(gain / math.log2(idx + 2) for idx, gain in enumerate(gains))


def ndcg_at_k(retrieved: list[str], grades: dict[str, int], k: int) -> float:
    """Normalized discounted cumulative gain at ``k`` using gain ``2^g - 1``."""
    _require_non_negative_k(k)
    actual_gains = [float((2 ** grades.get(doc_id, 0)) - 1) for doc_id in retrieved[:k]]
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    ideal_gains = [float((2**grade) - 1) for grade in ideal_grades]
    ideal = _dcg(ideal_gains)
    if ideal == 0:
        return 0.0
    return _dcg(actual_gains) / ideal


def mean_reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """Reciprocal rank of the first relevant document. 0 if none retrieved."""
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def aggregate_metrics(
    per_query: list[dict[str, float]],
) -> dict[str, float]:
    """Mean of each metric key across queries."""
    if not per_query:
        return {}
    keys = per_query[0].keys()
    return {key: sum(row[key] for row in per_query) / len(per_query) for key in keys}
