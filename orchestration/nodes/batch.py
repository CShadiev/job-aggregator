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

log = LoggerProvider.get_logger()


def make_batch_nodes(deps: PipelineDeps) -> dict[str, Any]:
    repository = deps.repository
    collection_service = deps.collection_service
    thread_id = deps.thread_id

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
                ))
        # Overwrite batch channels at cycle start so prior checkpoint lists do not stick.
        EMPTY_BATCH = []
        batch = [p.model_dump(mode="json") for p in result.postings]
        return {
            "cycle_id": cycle_id,
            "collected": EMPTY_BATCH,
            "normalize_failed": [],
            "unique_jobs": [],
            "pairs": [],
            "pair_results": Overwrite([]), }

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
                        "posting": failure.posting.model_dump(mode="json")},
                ))
        return {
            "collected": [p.model_dump(mode="json") for p in result.processed],
            "normalize_failed": [{"uid": f.posting.uid, "error": f.error} for f in result.failed], }

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
                ))
            raise
        return {}

    async def build_pairs(state: PipelineState) -> dict[str, Any]:
        cycle_id = state["cycle_id"]
        unique_jobs = state["unique_jobs"]
        profiles = await repository.get_user_profiles()
        usernames = [p.username for p in profiles]
        pairs = build_pair_list(usernames, unique_jobs)
        log.info(
            "Built {n_pairs} pairs from {n_jobs} jobs × {n_users} users",
            event="pipeline_build_pairs",
            cycle_id=cycle_id,
            n_pairs=len(pairs),
            n_jobs=len(unique_jobs),
            n_users=len(usernames),
        )
        return {"pairs": pairs}

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
            ) for pair in pairs]

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
        "build_pairs": build_pairs,
        "fanout": fanout,
        "finalize": finalize, }
