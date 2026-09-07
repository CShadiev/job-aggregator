"""CI smoke: index frozen gating benchmark and fail if gating quality regresses."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from benchmarks.retrieval.dataset import load_dataset
from benchmarks.retrieval.metrics import (
    fitting_recall_at_k,
    good_recall_at_k,
    mean_reciprocal_rank,
)
from search.client import build_opensearch_client
from search.models import IndexedJob, SearchFilters
from search.search_service import SearchService

_DATASET_DIR = Path("benchmarks/retrieval/dataset/05082026")
_BASELINE_PATH = _DATASET_DIR / "baseline.json"
_INDEX = "retrieval_smoke_jobs"


@pytest.fixture
async def search_service():
    """Fixture providing an ephemeral SearchService instance against OpenSearch."""
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
    """Verify that hybrid retrieval gating on the frozen candidate dataset meets the baseline floor."""
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
