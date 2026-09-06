"""Batch spine nodes: collect → normalize → dedupe → persist → build pairs → finalize."""

from typing import Any
from uuid import uuid4

from langgraph.types import Overwrite, Send

from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.failed_tasks import FailedTask
from orchestration.deps import PipelineDeps
from orchestration.state import (
    PipelineState,
    build_pair_list,
    cleared_batch_state,
    new_pair_state,
)
from search.models import IndexedJob, SearchFilters
from search.text import flatten_profile, job_embedding_text

log = LoggerProvider.get_logger()


def make_batch_nodes(deps: PipelineDeps) -> dict[str, Any]:
    """Construct node functions for the main batch pipeline spine."""
    repository = deps.repository
    collection_service = deps.collection_service
    thread_id = deps.thread_id
    search_service = deps.search_service
    embedding_client = deps.embedding_client
    pair_mode = deps.pair_mode
    retrieval_k = deps.retrieval_k

    async def collect(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"] or str(uuid4())
        _log = log.bind(event="pipeline_collect", cycle_id=cycle_id)
        result = await collection_service.collect()
        _log.info(
            "Collected {n_collected} jobs, {n_invalid} invalid",
            n_collected=len(result.postings),
            n_invalid=len(result.invalid_entries),
        )
        for invalid in result.invalid_entries:
            await repository.store_failed_task(
                FailedTask(
                    node="collect",
                    thread_id=thread_id,
                    cycle_id=cycle_id,
                    error=invalid.error,
                    payload={"entry": invalid.entry},
                )
            )
        # Overwrite batch channels at cycle start so prior checkpoint lists do not stick.
        return {
            "cycle_id": cycle_id,
            "collected": [p.model_dump(mode="json") for p in result.postings],
            "normalize_failed": [],
            "unique_jobs": [],
            "pairs": [],
            "pair_results": Overwrite([]),
        }

    async def normalize(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        collected = state["collected"]
        if not collected:
            log.info("No jobs to normalize", event="pipeline_normalize", cycle_id=cycle_id)
            return {"collected": [], "normalize_failed": []}

        postings = [JobPosting.model_validate(p) for p in collected]
        result = await collection_service.normalize(postings)
        log.info(
            "Normalized {n_processed} jobs, {n_failed} failed",
            event="pipeline_normalize",
            cycle_id=cycle_id,
            n_processed=len(result.processed),
            n_failed=len(result.failed),
        )
        for failure in result.failed:
            await repository.store_failed_task(
                FailedTask(
                    node="normalize",
                    thread_id=thread_id,
                    cycle_id=cycle_id,
                    error=failure.error,
                    payload={
                        "uid": failure.posting.uid,
                        "posting": failure.posting.model_dump(mode="json"),
                    },
                )
            )
        return {
            "collected": [p.model_dump(mode="json") for p in result.processed],
            "normalize_failed": [{"uid": f.posting.uid, "error": f.error} for f in result.failed],
        }

    async def dedupe(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        collected = state["collected"]
        if not collected:
            log.info("No jobs to deduplicate", event="pipeline_dedupe", cycle_id=cycle_id)
            return {"unique_jobs": []}

        postings = [JobPosting.model_validate(p) for p in collected]
        unique = await collection_service.deduplicate(postings)
        log.info(
            "Deduplicated to {n_unique} unique jobs from {n_input}",
            event="pipeline_dedupe",
            cycle_id=cycle_id,
            n_unique=len(unique),
            n_input=len(postings),
        )
        return {"unique_jobs": [p.model_dump(mode="json") for p in unique]}

    async def persist_jobs(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        unique_jobs = state["unique_jobs"]
        if not unique_jobs:
            log.info("No unique jobs to persist", event="pipeline_persist_jobs", cycle_id=cycle_id)
            return {}
        try:
            postings = [JobPosting.model_validate(p) for p in unique_jobs]
            await repository.upsert_jobs(postings)
            log.info(
                "Persisted {n_jobs} unique jobs",
                event="pipeline_persist_jobs",
                cycle_id=cycle_id,
                n_jobs=len(postings),
            )
        except Exception as exc:
            await repository.store_failed_task(
                FailedTask(
                    node="persist_jobs",
                    thread_id=thread_id,
                    cycle_id=cycle_id,
                    error=str(exc),
                    payload={"n_jobs": len(unique_jobs)},
                )
            )
            raise
        return {}

    async def embed_jobs(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        unique_jobs = state["unique_jobs"]
        if not unique_jobs:
            log.info("No unique jobs to embed", event="pipeline_embed_jobs", cycle_id=cycle_id)
            return {}
        try:
            postings = [JobPosting.model_validate(job) for job in unique_jobs]
            texts = [job_embedding_text(p.title, p.description_raw) for p in postings]
            vectors = await embedding_client.embed_texts(texts)
            docs = [
                IndexedJob.from_posting(posting, vector)
                for posting, vector in zip(postings, vectors, strict=True)
            ]
            await search_service.bulk_index_jobs(docs)
            log.info(
                "Indexed {n_jobs} jobs into OpenSearch",
                event="pipeline_embed_jobs",
                cycle_id=cycle_id,
                n_jobs=len(docs),
            )
        except Exception as exc:
            await repository.store_failed_task(
                FailedTask(
                    node="embed_jobs",
                    thread_id=thread_id,
                    cycle_id=cycle_id,
                    error=str(exc),
                    payload={"n_jobs": len(unique_jobs)},
                )
            )
            raise
        return {}

    async def build_pairs(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        unique_jobs = state["unique_jobs"]
        try:
            profiles = await repository.get_user_profiles()
            usernames = [p.username for p in profiles]
            if pair_mode == "cartesian":
                pairs = build_pair_list(usernames, unique_jobs)
            else:
                pairs = await _retrieve_topk_pairs(
                    unique_jobs=unique_jobs,
                    profiles=profiles,
                    k=retrieval_k,
                )
            n_pairs = len(pairs)
            n_jobs = len(unique_jobs)
            n_users = len(usernames)
            llm_calls_saved = max(n_users * n_jobs - n_pairs, 0)
            log.info(
                "Built {n_pairs} pairs from {n_jobs} jobs × {n_users} users",
                event="pipeline_build_pairs",
                cycle_id=cycle_id,
                n_pairs=n_pairs,
                n_jobs=n_jobs,
                n_users=n_users,
                k=retrieval_k,
                mode=pair_mode,
                llm_calls_saved=llm_calls_saved,
            )
        except Exception as exc:
            await repository.store_failed_task(
                FailedTask(
                    node="build_pairs",
                    thread_id=thread_id,
                    cycle_id=cycle_id,
                    error=str(exc),
                    payload={"n_jobs": len(unique_jobs), "mode": pair_mode},
                )
            )
            raise
        return {"pairs": pairs}

    async def _retrieve_topk_pairs(
        *,
        unique_jobs: list[dict[str, Any]],
        profiles: list,
        k: int,
    ) -> list[dict[str, Any]]:
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

    def fanout(state: PipelineState) -> list[Send] | str:
        pairs = state["pairs"]
        if not pairs:
            return "finalize"
        cycle_id = state["cycle_id"]
        return [
            Send(
                "pair_pipeline",
                new_pair_state(
                    cycle_id=cycle_id,
                    username=pair["username"],
                    job=pair["job"],
                ),
            )
            for pair in pairs
        ]

    async def finalize(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        pair_results = state["pair_results"]
        n_worth = sum(1 for r in pair_results if r.get("worth_full_assessment"))
        n_cover = sum(1 for r in pair_results if r.get("cover_letter_key"))
        n_skipped = sum(1 for r in pair_results if r.get("skipped_reason"))
        log.info(
            "Cycle complete: {n_pairs} pair results, {n_worth} worth assessment, "
            "{n_cover} cover letters, {n_skipped} skipped",
            event="pipeline_finalize",
            cycle_id=cycle_id,
            n_pairs=len(pair_results),
            n_worth=n_worth,
            n_cover=n_cover,
            n_skipped=n_skipped,
        )
        cleared = cleared_batch_state()
        cleared["pair_results"] = Overwrite([])
        return cleared

    return {
        "collect": collect,
        "normalize": normalize,
        "dedupe": dedupe,
        "persist_jobs": persist_jobs,
        "embed_jobs": embed_jobs,
        "build_pairs": build_pairs,
        "fanout": fanout,
        "finalize": finalize,
    }
