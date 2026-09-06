"""Unit tests for retrieval benchmark metrics and ATS grade conversion."""

from benchmarks.retrieval.labels import ats_score_to_grade
from benchmarks.retrieval.metrics import (
    aggregate_metrics,
    mean_reciprocal_rank,
    ndcg_at_k,
    recall_at_k,
)


def test_ats_score_to_grade_bands():
    """Test mapping of ATS percentage scores to discrete retrieval relevance grades."""
    assert ats_score_to_grade(80, screened_through=True) == 3
    assert ats_score_to_grade(79, screened_through=True) == 2
    assert ats_score_to_grade(60, screened_through=True) == 2
    assert ats_score_to_grade(59, screened_through=True) == 1
    assert ats_score_to_grade(90, screened_through=False) == 0
    assert ats_score_to_grade(None, screened_through=True) == 0


def test_recall_at_k():
    """Test Recall@k calculation for retrieved document sets."""
    retrieved = ["a", "b", "c"]
    assert recall_at_k(retrieved, {"a", "d"}, 2) == 0.5
    assert recall_at_k(retrieved, set(), 2) == 0.0


def test_ndcg_perfect_and_zero():
    """Test nDCG@k boundary conditions (perfect match vs zero match)."""
    grades = {"a": 3, "b": 1}
    assert ndcg_at_k(["a", "b"], grades, 2) == 1.0
    assert ndcg_at_k(["z", "y"], grades, 2) == 0.0


def test_mrr():
    """Test Mean Reciprocal Rank (MRR) computation."""
    assert mean_reciprocal_rank(["z", "a"], {"a"}) == 0.5
    assert mean_reciprocal_rank(["z"], {"a"}) == 0.0


def test_aggregate_metrics():
    """Test averaging per-query metric dictionaries."""
    assert aggregate_metrics([{"ndcg@10": 1.0}, {"ndcg@10": 0.5}]) == {"ndcg@10": 0.75}
    assert aggregate_metrics([]) == {}
