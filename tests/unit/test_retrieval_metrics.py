"""Unit tests for retrieval benchmark metrics, gating calculations, and ATS grade conversion."""

from pathlib import Path

from benchmarks.retrieval.dataset import load_dataset
from benchmarks.retrieval.labels import ats_score_to_grade
from benchmarks.retrieval.metrics import (
    aggregate_metrics,
    fitting_recall_at_k,
    gating_reduction_rate,
    good_recall_at_k,
    llm_calls_saved,
    mean_reciprocal_rank,
    moderate_recall_at_k,
    naive_recall_at_k,
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


def test_gating_recalls():
    """Test fitting, good, and moderate recall at k."""
    retrieved = ["g1", "m1", "low1", "g2", "low2"]
    good_uids = {"g1", "g2", "g3"}
    moderate_uids = {"m1", "m2"}
    fitting_uids = good_uids | moderate_uids

    # Top-2: contains g1, m1 (1/3 good, 1/2 moderate, 2/5 fitting)
    assert good_recall_at_k(retrieved, good_uids, 2) == 1.0 / 3.0
    assert moderate_recall_at_k(retrieved, moderate_uids, 2) == 0.5
    assert fitting_recall_at_k(retrieved, fitting_uids, 2) == 2.0 / 5.0

    # Top-4: contains g1, m1, low1, g2 (2/3 good, 1/2 moderate, 3/5 fitting)
    assert good_recall_at_k(retrieved, good_uids, 4) == 2.0 / 3.0
    assert moderate_recall_at_k(retrieved, moderate_uids, 4) == 0.5
    assert fitting_recall_at_k(retrieved, fitting_uids, 4) == 3.0 / 5.0


def test_gating_reduction_rate_and_llm_saved():
    """Test reduction rate percentage and count of LLM assessments saved."""
    total = 300
    assert gating_reduction_rate(20, total) == (300 - 20) / 300
    assert gating_reduction_rate(90, total) == (300 - 90) / 300
    assert gating_reduction_rate(300, total) == 0.0
    assert gating_reduction_rate(350, total) == 0.0
    assert gating_reduction_rate(20, 0) == 0.0

    assert llm_calls_saved(20, total) == 280
    assert llm_calls_saved(90, total) == 210
    assert llm_calls_saved(300, total) == 0
    assert llm_calls_saved(350, total) == 0


def test_naive_recall_at_k():
    """Test expected recall when randomly drawing k samples without replacement."""
    import pytest

    total = 300
    assert naive_recall_at_k(20, total) == 20.0 / 300.0
    assert naive_recall_at_k(50, total) == 50.0 / 300.0
    assert naive_recall_at_k(90, total) == 90.0 / 300.0
    assert naive_recall_at_k(150, total) == 0.5
    assert naive_recall_at_k(300, total) == 1.0
    assert naive_recall_at_k(400, total) == 1.0
    assert naive_recall_at_k(20, 0) == 0.0

    with pytest.raises(ValueError):
        naive_recall_at_k(0, total)


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


def test_load_dataset_gating_properties():
    """Test loading gating dataset 05082026 and verifying candidate and corpus properties."""
    dataset_dir = Path("benchmarks/retrieval/dataset/05082026")
    if not dataset_dir.exists():
        return

    dataset = load_dataset(dataset_dir)
    assert dataset.version == "05082026"
    assert len(dataset.corpus) == 300
    assert dataset.candidate is not None
    assert dataset.candidate.username == "cshadiev"
    assert len(dataset.candidate.query_vector) == 1536
    assert len(dataset.fitting_uids) == 90
    assert len(dataset.good_uids) == 30
    assert len(dataset.moderate_uids) == 60
    assert len(dataset.low_uids) == 210
    assert len(dataset.grades()) == 300
