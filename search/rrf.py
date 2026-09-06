"""Application-level Reciprocal Rank Fusion shared by search and benchmarks."""

from collections import defaultdict


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    k: int = 60,
    size: int | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked identifier lists with RRF.

    ``RRF_Score(d) = sum_m 1 / (k + rank_m(d))`` where ``rank`` is 1-based.
    Documents missing from a list contribute nothing from that modality.
    Returns ``(id, score)`` pairs ordered by descending score, then id.
    """
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] += 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if size is not None:
        return ordered[:size]
    return ordered
