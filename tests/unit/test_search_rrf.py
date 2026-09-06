"""Unit tests for Reciprocal Rank Fusion (RRF) ranking algorithm."""

from search.rrf import reciprocal_rank_fusion


def test_rrf_prefers_docs_high_in_both_lists():
    """Verify that documents ranked high across multiple retrieval lists receive highest score."""
    fused = reciprocal_rank_fusion(
        [
            ["a", "b", "c"],
            ["a", "c", "d"],
        ],
        k=60,
    )
    ids = [doc_id for doc_id, _score in fused]
    assert ids[0] == "a"
    scores = dict(fused)
    assert scores["a"] > scores["c"] > scores["b"]


def test_rrf_truncates_to_size():
    """Verify that RRF output list respects the requested maximum size."""
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"]], size=2)
    assert len(fused) == 2


def test_rrf_ignores_duplicate_ranks_in_one_list():
    """Verify that duplicate entries in the same ranked list are deduplicated."""
    fused = reciprocal_rank_fusion([["a", "a", "b"]])
    assert [doc_id for doc_id, _ in fused] == ["a", "b"]
