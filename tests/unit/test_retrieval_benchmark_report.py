"""The retrieval report headlines the production cutoff, not K=20."""

from scripts.run_retrieval_benchmark import _format_markdown_report, production_operating_k


def test_production_operating_k_is_half_the_corpus():
    k, ratio = production_operating_k(300)
    assert ratio == 0.5
    assert k == 150


def test_markdown_headline_uses_operating_k():
    report = {
        "timestamp": "20261005_000000",
        "dataset_version": "05082026",
        "candidate_username": "candidate",
        "n_corpus": 300,
        "n_fitting": 90,
        "n_good": 30,
        "n_moderate": 60,
        "n_low": 210,
        "operating_k": 150,
        "cutoffs": [20, 150],
        "metrics": {
            mode: {
                "mrr": 1.0,
                "good_recall@20": 0.2,
                "fitting_recall@20": 0.3,
                "naive_recall@20": 20 / 300,
                "reduction_rate@20": 280 / 300,
                "llm_calls_saved@20": 280,
                "moderate_recall@20": 0.1,
                "ndcg@20": 0.4,
                "good_recall@150": 0.8,
                "fitting_recall@150": 0.7,
                "moderate_recall@150": 0.6,
                "naive_recall@150": 0.5,
                "reduction_rate@150": 0.5,
                "llm_calls_saved@150": 150,
                "ndcg@150": 0.5,
            }
            for mode in ("bm25", "knn", "hybrid")
        },
    }
    markdown = _format_markdown_report(report)
    assert "Headline Production Gating Metrics (K=150)" in markdown
    assert "Good Recall@150" in markdown
    assert "K=20 (Production Default)" not in markdown
    assert "| hybrid | 0.8000 | 0.7000 | 0.5000 | 50.0% | 150 | 1.0000 |" in markdown
