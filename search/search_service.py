"""OpenSearch SearchService for corpus retrieval and the assessed-job feed."""

from __future__ import annotations

import asyncio
from typing import Any

from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import NotFoundError

from config import Config, ConfigProvider
from logger_provider import LoggerProvider
from models.generics import PaginatedDataResponse
from models.job_application import JobApplicationStatus
from models.jobs_api import JobFeedItem, JobFeedQuery, JobFeedSortField, SortOrder
from search.mappings import ASSESSMENTS_INDEX_SETTINGS, JOBS_INDEX_SETTINGS
from search.models import (
    DenormalizedAssessment,
    IndexedJob,
    SearchFilters,
    SearchHit,
    SearchHits,
    SearchMode,
    assessment_document_id,
)
from search.rrf import reciprocal_rank_fusion
from telemetry import get_tracer

log = LoggerProvider.get_logger()
tracer = get_tracer("job-aggregator.search")

_RRF_K = 60
_HYBRID_OVERFETCH = 50
_REFRESH = {"refresh": "wait_for"}


class SearchService:
    """Provides high-level indexing, retrieval (BM25, k-NN, hybrid), and feed query services over OpenSearch."""

    def __init__(
        self,
        client: AsyncOpenSearch,
        *,
        jobs_index: str | None = None,
        assessments_index: str | None = None,
        config: Config | None = None,
    ) -> None:
        """Initialize SearchService with an OpenSearch client and index settings.

        Args:
            client: AsyncOpenSearch client instance.
            jobs_index: Optional override for the jobs index name.
            assessments_index: Optional override for the assessments index name.
            config: Optional application Config override.
        """
        cfg = config or ConfigProvider.get_config()
        self._client = client
        self.jobs_index = jobs_index or cfg.OPENSEARCH_INDEX_NAME
        self.assessments_index = assessments_index or cfg.OPENSEARCH_ASSESSMENTS_INDEX_NAME

    async def ping(self) -> bool:
        """Check whether the OpenSearch cluster is reachable and healthy."""
        try:
            return bool(await self._client.ping())
        except Exception as exc:
            log.warning("OpenSearch ping failed: {exc}", exc=str(exc))
            return False

    async def close(self) -> None:
        """Close the underlying AsyncOpenSearch client connections."""
        await self._client.close()

    async def ensure_indices(self) -> None:
        """Ensure that the jobs and assessments indices exist with appropriate mappings and settings."""
        await self._ensure_index(self.jobs_index, JOBS_INDEX_SETTINGS)
        await self._ensure_index(self.assessments_index, ASSESSMENTS_INDEX_SETTINGS)

    async def _ensure_index(self, name: str, body: dict) -> None:
        """Create an OpenSearch index if it does not already exist."""
        if await self._client.indices.exists(index=name):
            return
        await self._client.indices.create(index=name, body=body)
        log.info("Created OpenSearch index {index}", index=name)

    async def bulk_index_jobs(self, docs: list[IndexedJob]) -> None:
        """Bulk index documents into the jobs corpus index.

        Args:
            docs: List of IndexedJob models to index.
        """
        if not docs:
            return
        actions: list[dict[str, Any]] = []
        for doc in docs:
            actions.append({"index": {"_index": self.jobs_index, "_id": doc.uid}})
            actions.append(doc.model_dump(mode="json"))
        response = await self._client.bulk(body=actions, params=_REFRESH)
        _raise_if_bulk_errors(response, "jobs")

    async def index_assessment(self, doc: DenormalizedAssessment) -> None:
        """Index or update a single denormalized candidate-job assessment document.

        Args:
            doc: DenormalizedAssessment instance to store.
        """
        await self._client.index(
            index=self.assessments_index,
            id=doc.document_id(),
            body=doc.to_opensearch_source(),
            params=_REFRESH,
        )

    async def bulk_index_assessments(self, docs: list[DenormalizedAssessment]) -> None:
        """Bulk index denormalized assessment documents into the assessments index.

        Args:
            docs: List of DenormalizedAssessment models to index.
        """
        if not docs:
            return
        actions: list[dict[str, Any]] = []
        for doc in docs:
            actions.append({"index": {"_index": self.assessments_index, "_id": doc.document_id()}})
            actions.append(doc.to_opensearch_source())
        response = await self._client.bulk(body=actions, params=_REFRESH)
        _raise_if_bulk_errors(response, "assessments")

    async def update_assessment_status(
        self, username: str, job_uid: str, status: JobApplicationStatus
    ) -> None:
        """Update the application status sub-document for an assessed job.

        Args:
            username: Candidate username.
            job_uid: Job identifier.
            status: Updated JobApplicationStatus model.
        """
        doc_id = assessment_document_id(username, job_uid)
        try:
            await self._client.update(
                index=self.assessments_index,
                id=doc_id,
                body={"doc": {"status": status.model_dump(mode="json")}},
                params=_REFRESH,
            )
        except NotFoundError:
            log.warning(
                "OpenSearch assessment missing for status update {username}/{job_uid}",
                username=username,
                job_uid=job_uid,
            )

    async def search_jobs(
        self,
        *,
        query_text: str | None,
        query_vector: list[float] | None,
        filters: SearchFilters | None = None,
        mode: SearchMode = "hybrid",
        size: int = 20,
    ) -> SearchHits:
        """Search the jobs corpus using BM25, k-NN vector search, or hybrid RRF fusion.

        Args:
            query_text: Free-text search query (required for BM25 and hybrid).
            query_vector: Embedding vector (required for k-NN and hybrid).
            filters: Structured metadata filters.
            mode: Search mode ("bm25", "knn", or "hybrid").
            size: Number of top results to return.

        Returns:
            SearchHits containing matched items and total hit count.
        """
        with tracer.start_as_current_span("search.jobs") as span:
            span.set_attribute("search.mode", mode)
            span.set_attribute("search.size", size)
            filters = filters or SearchFilters()
            if mode == "bm25":
                if not query_text:
                    raise ValueError("query_text is required for BM25 search")
                return await self._search_bm25(query_text, filters, size)
            if mode == "knn":
                if not query_vector:
                    raise ValueError("query_vector is required for k-NN search")
                return await self._search_knn(query_vector, filters, size)
            if not query_text or not query_vector:
                raise ValueError("hybrid search requires query_text and query_vector")
            return await self._search_hybrid(query_text, query_vector, filters, size)

    async def search_user_feed(
        self,
        *,
        username: str,
        query: JobFeedQuery,
        page: int,
        page_size: int,
    ) -> PaginatedDataResponse[JobFeedItem]:
        """Execute a structured filter and sort query against the candidate's assessed jobs feed.

        Args:
            username: Candidate username.
            query: Query criteria including search terms, match score ranges, and status flags.
            page: 1-indexed page number.
            page_size: Number of items per page.

        Returns:
            PaginatedDataResponse containing JobFeedItem list and total count.
        """
        with tracer.start_as_current_span("search.user_feed") as span:
            span.set_attribute("search.page", page)
            span.set_attribute("search.page_size", page_size)
            body = _user_feed_query_body(username, query, page, page_size)
            response = await self._client.search(index=self.assessments_index, body=body)
            hits = response.get("hits", {})
            total = _total_hits(hits)
            items: list[JobFeedItem] = []
            for hit in hits.get("hits", []):
                source = hit.get("_source") or {}
                items.append(DenormalizedAssessment.from_opensearch_source(source).to_feed_item())
            return PaginatedDataResponse(data=items, page=page, page_size=page_size, total=total)

    async def _search_bm25(self, query_text: str, filters: SearchFilters, size: int) -> SearchHits:
        """Execute a BM25 multi-match search over job title and description."""
        body = {
            "size": size,
            "query": {
                "bool": {
                    "must": [_multi_match(query_text)],
                    "filter": _jobs_filter_clauses(filters),
                }
            },
        }
        return await self._execute_jobs_search(body)

    async def _search_knn(
        self, query_vector: list[float], filters: SearchFilters, size: int
    ) -> SearchHits:
        """Execute an HNSW vector similarity search over job embeddings."""
        knn: dict[str, Any] = {
            "embedding": {
                "vector": query_vector,
                "k": size,
            }
        }
        filter_clauses = _jobs_filter_clauses(filters)
        if filter_clauses:
            knn["embedding"]["filter"] = _single_or_bool_filter(filter_clauses)
        body = {"size": size, "query": {"knn": knn}}
        return await self._execute_jobs_search(body)

    async def _search_hybrid(
        self,
        query_text: str,
        query_vector: list[float],
        filters: SearchFilters,
        size: int,
    ) -> SearchHits:
        """Execute parallel BM25 and k-NN searches and fuse ranked results using Reciprocal Rank Fusion."""
        fetch = max(size, _HYBRID_OVERFETCH)
        bm25_hits, knn_hits = await asyncio.gather(
            self._search_bm25(query_text, filters, fetch),
            self._search_knn(query_vector, filters, fetch),
        )
        fused = reciprocal_rank_fusion(
            [[hit.uid for hit in bm25_hits.hits], [hit.uid for hit in knn_hits.hits]],
            k=_RRF_K,
            size=size,
        )
        by_uid = {hit.uid: hit for hit in knn_hits.hits}
        by_uid.update({hit.uid: hit for hit in bm25_hits.hits})
        hits = [
            SearchHit(uid=uid, score=score, source=by_uid[uid].source)
            for uid, score in fused
            if uid in by_uid
        ]
        return SearchHits(hits=hits, total=len(hits))

    async def _execute_jobs_search(self, body: dict[str, Any]) -> SearchHits:
        """Send search query DSL to the jobs index and extract SearchHits."""
        response = await self._client.search(index=self.jobs_index, body=body)
        hits_block = response.get("hits", {})
        hits = [
            SearchHit(
                uid=hit["_source"]["uid"],
                score=float(hit.get("_score") or 0.0),
                source=hit.get("_source") or {},
            )
            for hit in hits_block.get("hits", [])
        ]
        return SearchHits(hits=hits, total=_total_hits(hits_block))


def _multi_match(query_text: str) -> dict[str, Any]:
    """Generate OpenSearch multi_match query clause boosting title over description."""
    return {
        "multi_match": {
            "query": query_text,
            "fields": ["title^2", "description"],
            "type": "best_fields",
        }
    }


def _jobs_filter_clauses(filters: SearchFilters) -> list[dict[str, Any]]:
    """Build OpenSearch bool filter clauses from structured SearchFilters."""
    clauses: list[dict[str, Any]] = []
    if filters.uids:
        clauses.append({"terms": {"uid": filters.uids}})
    if filters.remote is not None:
        clauses.append({"term": {"remote": filters.remote}})
    if filters.sources:
        clauses.append({"terms": {"source": filters.sources}})
    if filters.location:
        clauses.append({"term": {"location": filters.location}})
    return clauses


def _single_or_bool_filter(clauses: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap one or more filter clauses in a single filter dict or bool container."""
    if len(clauses) == 1:
        return clauses[0]
    return {"bool": {"filter": clauses}}


def _user_feed_query_body(
    username: str, query: JobFeedQuery, page: int, page_size: int
) -> dict[str, Any]:
    """Build OpenSearch request body DSL for querying user feed items with filtering and pagination."""
    filters: list[dict[str, Any]] = [{"term": {"username": username}}]
    if query.min_cv_ats_match_score is not None:
        filters.append({"range": {"cv_ats_match_score": {"gte": query.min_cv_ats_match_score}}})
    if query.min_profile_ats_match_score is not None:
        filters.append(
            {"range": {"profile_ats_match_score": {"gte": query.min_profile_ats_match_score}}}
        )
    if query.exclude_deal_breakers:
        filters.append({"bool": {"must_not": [{"exists": {"field": "deal_breakers"}}]}})
    if query.remote is not None:
        filters.append({"term": {"job.remote": query.remote}})
    if query.sources:
        filters.append({"terms": {"job.source": query.sources}})
    if query.tags:
        filters.append({"terms": {"job.tags": query.tags}})
    if query.location:
        filters.append(
            {
                "wildcard": {
                    "job.location": {
                        "value": f"*{query.location}*",
                        "case_insensitive": True,
                    }
                }
            }
        )

    filters.append({"term": {"status.applied": query.applied}})
    filters.append({"term": {"status.skipped": query.skipped}})
    if query.active_only:
        filters.append({"term": {"status.active": True}})
    if query.application_stage is not None:
        filters.append({"term": {"status.stage": query.application_stage.value}})

    must: list[dict[str, Any]] = []
    q = (query.q or "").strip()
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["job.title^3", "job.company^2", "job.description"],
                    "type": "best_fields",
                }
            }
        )

    sort_field = {
        JobFeedSortField.POSTED_AT: "job.posted_at",
        JobFeedSortField.CV_ATS_MATCH_SCORE: "cv_ats_match_score",
        JobFeedSortField.PROFILE_ATS_MATCH_SCORE: "profile_ats_match_score",
    }[query.sort_by]
    sort_dir = "asc" if query.sort_order == SortOrder.ASC else "desc"
    from_offset = (page - 1) * page_size

    bool_query: dict[str, Any] = {"filter": filters}
    if must:
        bool_query["must"] = must
    else:
        bool_query["must"] = [{"match_all": {}}]

    return {
        "from": from_offset,
        "size": page_size,
        "track_total_hits": True,
        "query": {"bool": bool_query},
        "sort": [{sort_field: {"order": sort_dir}}, {"job_uid": {"order": "asc"}}],
    }


def _total_hits(hits_block: dict[str, Any]) -> int:
    """Extract integer total hit count from OpenSearch hits payload."""
    total = hits_block.get("total", 0)
    if isinstance(total, dict):
        return int(total.get("value") or 0)
    return int(total or 0)


def _raise_if_bulk_errors(response: dict[str, Any], label: str) -> None:
    """Raise RuntimeError if an OpenSearch bulk indexing response contains errors."""
    if not response.get("errors"):
        return
    items = response.get("items") or []
    reasons = []
    for item in items:
        payload = next(iter(item.values()), {})
        error = payload.get("error")
        if error:
            reasons.append(error.get("reason") or str(error))
        if len(reasons) >= 5:
            break
    raise RuntimeError(f"OpenSearch bulk index of {label} failed: {'; '.join(reasons)}")
