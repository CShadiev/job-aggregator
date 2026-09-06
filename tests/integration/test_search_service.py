"""Integration tests for SearchService against a live OpenSearch node."""

from datetime import UTC, datetime

import pytest

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.generics import PaginatedDataRequest
from models.job_application import JobApplicationStatus
from models.jobs_api import JobFeedQuery
from search.client import build_opensearch_client
from search.models import DenormalizedAssessment, IndexedJob, SearchFilters
from search.rrf import reciprocal_rank_fusion
from search.search_service import SearchService
from search.text import job_embedding_text


def _vector(on_at: int, dim: int = 1536) -> list[float]:
    values = [0.0] * dim
    values[on_at % dim] = 1.0
    return values


def _job(uid: str, title: str, description: str) -> JobPosting:
    return JobPosting(
        uid=uid,
        source="test",
        title=title,
        company="Acme",
        location="Berlin",
        remote=True,
        url=f"https://example.com/{uid}",
        description_raw=f"<p>{description}</p>",
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
async def search_service():
    client = build_opensearch_client()
    if not await client.ping():
        await client.close()
        pytest.skip("OpenSearch is not reachable")
    service = SearchService(
        client,
        jobs_index="itest_jobs",
        assessments_index="itest_assessments",
    )
    for index in (service.jobs_index, service.assessments_index):
        if await client.indices.exists(index=index):
            await client.indices.delete(index=index)
    await service.ensure_indices()
    try:
        yield service
    finally:
        for index in (service.jobs_index, service.assessments_index):
            if await client.indices.exists(index=index):
                await client.indices.delete(index=index)
        await service.close()


@pytest.mark.asyncio
async def test_bm25_knn_and_hybrid_return_hits(search_service: SearchService):
    python_job = _job("j-py", "Python Backend Engineer", "FastAPI MongoDB Python APIs")
    react_job = _job("j-js", "React Frontend Engineer", "TypeScript React CSS")
    await search_service.bulk_index_jobs(
        [
            IndexedJob.from_posting(python_job, _vector(0)),
            IndexedJob.from_posting(react_job, _vector(1)),
        ]
    )

    bm25 = await search_service.search_jobs(
        query_text="Python FastAPI",
        query_vector=None,
        filters=SearchFilters(),
        mode="bm25",
        size=5,
    )
    assert bm25.hits
    assert bm25.hits[0].uid == "j-py"

    knn = await search_service.search_jobs(
        query_text=None,
        query_vector=_vector(0),
        filters=SearchFilters(uids=["j-py", "j-js"]),
        mode="knn",
        size=5,
    )
    assert knn.hits
    assert knn.hits[0].uid == "j-py"

    hybrid = await search_service.search_jobs(
        query_text=job_embedding_text(python_job.title, python_job.description_raw),
        query_vector=_vector(0),
        filters=SearchFilters(uids=["j-py", "j-js"]),
        mode="hybrid",
        size=5,
    )
    assert {hit.uid for hit in hybrid.hits} <= {"j-py", "j-js"}
    fused = reciprocal_rank_fusion([[h.uid for h in bm25.hits], [h.uid for h in knn.hits]])
    assert fused[0][0] == "j-py"


@pytest.mark.asyncio
async def test_search_user_feed_keyword_and_filters(search_service: SearchService):
    job = _job("feed-1", "Kubernetes Platform Engineer", "Terraform Go Kubernetes")
    assessment = FitAssessment(
        cv_ats_match_score=88,
        profile_ats_match_score=90,
        deal_breakers=[],
        summary="Strong platform fit.",
    )
    status = JobApplicationStatus(username="ada", job_uid=job.uid, applied=False, skipped=False)
    await search_service.index_assessment(
        DenormalizedAssessment.from_parts(
            assessment=assessment, username="ada", job=job, status=status
        )
    )

    request = PaginatedDataRequest[JobFeedQuery](
        query=JobFeedQuery(q="Kubernetes", skipped=False, min_cv_ats_match_score=80),
        page=1,
        page_size=10,
    )
    response = await search_service.search_user_feed(
        username="ada", query=request.query, page=request.page, page_size=request.page_size
    )
    assert response.total == 1
    assert response.data[0].job.uid == "feed-1"
    assert response.data[0].fit.cv_ats_match_score == 88

    empty = await search_service.search_user_feed(
        username="ada",
        query=JobFeedQuery(q="iOS Swift", skipped=False),
        page=1,
        page_size=10,
    )
    assert empty.total == 0
