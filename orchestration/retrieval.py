"""Top-K hybrid retrieval used by the scheduled pipeline and the demo seed script."""

from collections.abc import Sequence
from math import ceil
from typing import Any

from models.users import UserProfile
from search.embeddings import EmbeddingClient
from search.models import SearchFilters
from search.search_service import SearchService
from search.text import flatten_profile


def retrieval_size(n_jobs: int, *, ratio: float, min_k: int, max_k: int) -> int:
    """Scale the top-K cutoff to a share of the current batch, clamped to the configured bounds."""
    return min(max(ceil(n_jobs * ratio), min_k), max_k)


async def retrieve_topk_pairs(
    *,
    unique_jobs: list[dict[str, Any]],
    profiles: Sequence[UserProfile],
    k: int,
    embedding_client: EmbeddingClient,
    search_service: SearchService,
) -> list[dict[str, Any]]:
    """Return per-profile hybrid hits restricted to *unique_jobs*, shaped for pair fan-out."""
    if not unique_jobs or not profiles:
        return []
    jobs_by_uid = {job["uid"]: job for job in unique_jobs}
    uids = list(jobs_by_uid)
    pairs: list[dict[str, Any]] = []
    for profile in profiles:
        query_text = flatten_profile(profile)
        query_vector = await embedding_client.embed_profile(profile)
        hits = await search_service.search_jobs(
            query_text=query_text,
            query_vector=query_vector,
            filters=SearchFilters(uids=uids),
            mode="hybrid",
            size=k,
        )
        for hit in hits.hits:
            job = jobs_by_uid.get(hit.uid)
            if job is None:
                continue
            pairs.append({"username": profile.username, "job_uid": job["uid"], "job": job})
    return pairs
