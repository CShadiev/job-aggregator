"""CI smoke: index a frozen split and fail if nDCG@10 regresses."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from benchmarks.retrieval.dataset import load_dataset
from benchmarks.retrieval.metrics import ndcg_at_k
from search.client import build_opensearch_client
from search.models import IndexedJob, SearchFilters
from search.search_service import SearchService

_DATASET_DIR = Path("benchmarks/retrieval/dataset/06092026")
_BASELINE_PATH = _DATASET_DIR / "baseline.json"
_INDEX = "retrieval_smoke_jobs"


@pytest.fixture
async def search_service():
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


async def test_hybrid_ndcg_meets_baseline(search_service: SearchService):
    dataset = load_dataset(_DATASET_DIR).smoke_subset()
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
            posted_at=datetime.fromisoformat(doc.posted_at.replace("Z", "+00:00")),
        )
        for doc in dataset.corpus
    ]
    await search_service.bulk_index_jobs(docs)

    scores: list[float] = []
    for query in dataset.queries:
        hits = await search_service.search_jobs(
            query_text=query.text,
            query_vector=query.embedding,
            filters=SearchFilters(),
            mode="hybrid",
            size=10,
        )
        retrieved = [hit.uid for hit in hits.hits]
        assert retrieved, f"hybrid search returned no hits for {query.query_id}"
        scores.append(ndcg_at_k(retrieved, dataset.grades(query.query_id), 10))

    mean_ndcg = sum(scores) / len(scores)
    floor = float(baseline["hybrid_ndcg_at_10"])
    assert mean_ndcg + 1e-9 >= floor, (
        f"hybrid nDCG@10 {mean_ndcg:.4f} dropped below baseline {floor:.4f}"
    )
