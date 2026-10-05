"""Retrieval regression checks.

The OpenSearch re-index test is a maintainer check: it skips when the private
corpus is absent. CI asserts the committed hybrid ranked-uid list against
``baseline.json`` using gold labels from the public screening results.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from benchmarks.retrieval.composition import (
    COMPOSED_JSON_PATH,
    RANKED_UIDS_PATH,
    compose_from_disk,
    load_screening_results,
)
from benchmarks.retrieval.dataset import load_dataset
from benchmarks.retrieval.metrics import (
    fitting_recall_at_k,
    good_recall_at_k,
    mean_reciprocal_rank,
)
from scripts.run_retrieval_benchmark import production_operating_k
from search.client import build_opensearch_client
from search.models import IndexedJob, SearchFilters
from search.search_service import SearchService

_DATASET_DIR = Path("benchmarks/retrieval/dataset/05082026")
_BASELINE_PATH = _DATASET_DIR / "baseline.json"
_CORPUS_PATH = _DATASET_DIR / "corpus.jsonl"
_CANDIDATE_PATH = _DATASET_DIR / "candidate.json"
_INDEX = "retrieval_smoke_jobs"


def _private_corpus_available() -> bool:
    return _CORPUS_PATH.is_file() and _CANDIDATE_PATH.is_file()


@pytest.fixture
async def search_service():
    """Fixture providing an ephemeral SearchService instance against OpenSearch."""
    if not _private_corpus_available():
        pytest.skip("Retrieval corpus is private and not present")
    client = build_opensearch_client()
    if not await client.ping():
        await client.close()
        pytest.skip("OpenSearch is not reachable")
    service = SearchService(
        client, jobs_index=_INDEX, assessments_index="retrieval_smoke_assessments"
    )
    if await client.indices.exists(index=_INDEX):
        await client.indices.delete(index=_INDEX)
    await service.ensure_indices()
    try:
        yield service
    finally:
        if await client.indices.exists(index=_INDEX):
            await client.indices.delete(index=_INDEX)
        if await client.indices.exists(index="retrieval_smoke_assessments"):
            await client.indices.delete(index="retrieval_smoke_assessments")
        await service.close()


async def test_hybrid_gating_meets_baseline(search_service: SearchService):
    """Maintainer check: re-index the private corpus and compare hybrid search to the floor.

    Skipped when the corpus is not on disk. GitHub CI does not run this test.
    """
    if not _private_corpus_available():
        pytest.skip("Retrieval corpus is private and not present")
    dataset = load_dataset(_DATASET_DIR)
    baseline = json.loads(_BASELINE_PATH.read_text())
    docs = [
        IndexedJob(
            uid=doc.uid,
            title=doc.title,
            description=doc.description,
            embedding=doc.embedding,
            source=doc.source,
            company=doc.company,
            location=doc.location,
            url=doc.url or f"https://example.com/{doc.uid}",
            remote=doc.remote,
            job_types=doc.job_types,
            posted_at=datetime.fromisoformat(doc.posted_at.replace("Z", "+00:00")),
        )
        for doc in dataset.corpus
    ]
    await search_service.bulk_index_jobs(docs)

    candidate = dataset.candidate
    assert candidate is not None, "Gating dataset must contain candidate.json"

    hits = await search_service.search_jobs(
        query_text=candidate.query_text,
        query_vector=candidate.query_vector,
        filters=SearchFilters(),
        mode="hybrid",
        size=150,
    )
    retrieved = [hit.uid for hit in hits.hits]
    assert retrieved, "Hybrid search returned no hits for candidate query"

    mrr = mean_reciprocal_rank(retrieved, dataset.fitting_uids)
    floor_mrr = float(baseline.get("hybrid_mrr", 1.0))
    assert mrr + 1e-9 >= floor_mrr, f"Hybrid MRR {mrr:.4f} dropped below baseline {floor_mrr:.4f}"

    good_recall_20 = good_recall_at_k(retrieved, dataset.good_uids, 20)
    floor_good_20 = float(baseline.get("hybrid_good_recall_at_20", 0.15))
    assert good_recall_20 + 1e-9 >= floor_good_20, (
        f"Hybrid good_recall@20 {good_recall_20:.4f} dropped below baseline {floor_good_20:.4f}"
    )

    fitting_recall_90 = fitting_recall_at_k(retrieved, dataset.fitting_uids, 90)
    floor_fitting_90 = float(baseline.get("hybrid_fitting_recall_at_90", 0.45))
    assert fitting_recall_90 + 1e-9 >= floor_fitting_90, (
        f"Hybrid fitting_recall@90 {fitting_recall_90:.4f} dropped below baseline {floor_fitting_90:.4f}"
    )

    fitting_recall_150 = fitting_recall_at_k(retrieved, dataset.fitting_uids, 150)
    floor_fitting_150 = float(baseline.get("hybrid_fitting_recall_at_150", 0.70))
    assert fitting_recall_150 + 1e-9 >= floor_fitting_150, (
        f"Hybrid fitting_recall@150 {fitting_recall_150:.4f} dropped below baseline {floor_fitting_150:.4f}"
    )


def test_committed_hybrid_ranking_meets_baseline():
    """Assert the public hybrid ranked-uid list against the committed recall floor."""
    ranked = json.loads(RANKED_UIDS_PATH.read_text(encoding="utf-8"))
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    assert ranked["dataset_version"] == baseline["dataset_version"] == "05082026"
    assert ranked["mode"] == "hybrid"
    uids = list(ranked["ranked_uids"])
    operating_k, _ratio = production_operating_k(int(ranked["n_corpus"]))
    assert int(ranked["operating_k"]) == operating_k
    assert len(uids) >= operating_k

    _meta, rows = load_screening_results(Path(ranked["screening_results"]))
    by_uid = {row.job_uid: row for row in rows}
    missing = [uid for uid in uids if uid not in by_uid]
    assert not missing, f"{len(missing)} ranked uids missing from screening results"
    good = {row.job_uid for row in rows if row.cv_category == "good"}
    fitting = {
        row.job_uid
        for row in rows
        if row.worth_full_assessment_gold or row.cv_category in {"good", "moderate"}
    }

    mrr = mean_reciprocal_rank(uids, fitting)
    floor_mrr = float(baseline["hybrid_mrr"])
    assert mrr + 1e-9 >= floor_mrr, f"Hybrid MRR {mrr:.4f} dropped below baseline {floor_mrr:.4f}"

    good_recall_20 = good_recall_at_k(uids, good, 20)
    floor_good_20 = float(baseline["hybrid_good_recall_at_20"])
    assert good_recall_20 + 1e-9 >= floor_good_20, (
        f"Hybrid good_recall@20 {good_recall_20:.4f} dropped below baseline {floor_good_20:.4f}"
    )

    fitting_recall_90 = fitting_recall_at_k(uids, fitting, 90)
    floor_fitting_90 = float(baseline["hybrid_fitting_recall_at_90"])
    assert fitting_recall_90 + 1e-9 >= floor_fitting_90, (
        f"Hybrid fitting_recall@90 {fitting_recall_90:.4f} dropped below baseline {floor_fitting_90:.4f}"
    )

    good_recall_150 = good_recall_at_k(uids, good, 150)
    floor_good_150 = float(baseline["hybrid_good_recall_at_150"])
    assert good_recall_150 + 1e-9 >= floor_good_150, (
        f"Hybrid good_recall@150 {good_recall_150:.4f} dropped below baseline {floor_good_150:.4f}"
    )

    fitting_recall_150 = fitting_recall_at_k(uids, fitting, 150)
    floor_fitting_150 = float(baseline["hybrid_fitting_recall_at_150"])
    assert fitting_recall_150 + 1e-9 >= floor_fitting_150, (
        f"Hybrid fitting_recall@150 {fitting_recall_150:.4f} dropped below baseline {floor_fitting_150:.4f}"
    )


def test_composed_gate_report_matches_public_inputs():
    """The committed composition report is exactly the replay of the public artifacts."""
    committed = json.loads(COMPOSED_JSON_PATH.read_text(encoding="utf-8"))
    recomputed = compose_from_disk()
    assert committed == recomputed
