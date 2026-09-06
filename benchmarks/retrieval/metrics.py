"""Ranking metrics for the retrieval benchmark. Pure functions, no I/O."""

from __future__ import annotations

import math


def _require_non_negative_k(k: int) -> None:
    if k < 1:
        raise ValueError("k must be >= 1")


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant documents appearing in the top-``k`` retrieved."""
    _require_non_negative_k(k)
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def _dcg(gains: list[float]) -> float:
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
