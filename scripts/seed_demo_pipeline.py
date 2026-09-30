"""Run retrieval and the pair subgraph for the demo user over recent stored jobs."""

from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from aiohttp import ClientSession
from botocore.exceptions import ClientError
from pymongo import AsyncMongoClient

from config import ConfigProvider
from cv_text_service import ensure_cv_text
from demo import DEMO_PIPELINE_THREAD_ID
from job_submit_service import MANUAL_JOB_SOURCE
from logger_provider import LoggerProvider
from monitoring.pricing import configure_pricing
from orchestration.deps import PipelineDeps, build_deps
from orchestration.graph import build_pair_subgraph
from orchestration.retrieval import retrieval_size, retrieve_topk_pairs
from orchestration.state import new_pair_state
from telemetry import configure_langsmith, cycle_id_ctx, setup_telemetry

log = LoggerProvider.get_logger()


async def run_demo_pipeline(
    *,
    limit: int,
    username: str,
    deps: PipelineDeps,
    concurrency: int,
) -> int:
    """Retrieve top-K jobs for *username* and invoke the pair subgraph for each hit.

    Does not collect new postings. Jobs missing from the OpenSearch jobs index
    simply do not appear as hits.
    """
    repository = deps.repository
    profile = await repository.get_user_profile(username)
    if profile is None:
        raise SystemExit(f"User profile not found: {username}")
    try:
        deps.object_storage.get_user_cv(username)
    except ClientError as exc:
        raise SystemExit(f"User CV not found: {username}") from exc

    postings = await repository.get_recent_jobs(limit=limit, exclude_source=MANUAL_JOB_SOURCE)
    unique_jobs = [posting.model_dump(mode="json") for posting in postings]
    n_jobs = len(unique_jobs)
    if n_jobs == 0:
        log.info(
            "No non-manual jobs to seed",
            event="demo_pipeline_empty",
            username=username,
            limit=limit,
        )
        return 0

    artifact = await ensure_cv_text(
        username=username,
        repository=repository,
        object_storage=deps.object_storage,
        agent=deps.cv_text_extraction_agent,
    )
    k = retrieval_size(
        n_jobs,
        ratio=deps.retrieval_ratio,
        min_k=deps.retrieval_min_k,
        max_k=deps.retrieval_max_k,
    )
    pairs = await retrieve_topk_pairs(
        unique_jobs=unique_jobs,
        profiles=[profile],
        k=k,
        embedding_client=deps.embedding_client,
        search_service=deps.search_service,
    )
    for pair in pairs:
        pair["cv_text"] = artifact.cv_text
    n_pairs = len(pairs)
    log.info(
        "Demo pipeline retrieval: {n_jobs} jobs, k={k}, {n_pairs} pairs",
        event="demo_pipeline_retrieval",
        username=username,
        n_jobs=n_jobs,
        k=k,
        n_pairs=n_pairs,
        limit=limit,
    )
    if not pairs:
        return 0

    pair_graph = build_pair_subgraph(deps)
    cycle_id = str(uuid4())
    token = cycle_id_ctx.set(cycle_id)
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_pair(pair: dict) -> None:
        async with semaphore:
            await pair_graph.ainvoke(
                new_pair_state(
                    cycle_id=cycle_id,
                    username=pair["username"],
                    cv_text=pair["cv_text"],
                    job=pair["job"],
                )
            )

    try:
        await asyncio.gather(*[_run_pair(pair) for pair in pairs])
    finally:
        cycle_id_ctx.reset(token)
    log.info(
        "Demo pipeline finished {n_pairs} pair runs",
        event="demo_pipeline_end",
        username=username,
        cycle_id=cycle_id,
        n_pairs=n_pairs,
    )
    return n_pairs


async def _async_main(limit: int) -> None:
    """Build pipeline deps and run the demo pair seed."""
    config = ConfigProvider.get_config()
    if not config.DEMO_USERNAME:
        raise SystemExit("DEMO_USERNAME is not set")
    setup_telemetry()
    configure_langsmith()
    mongo = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    deps: PipelineDeps | None = None
    try:
        configure_pricing(mongo, config=config)
        async with ClientSession() as client_session:
            deps = await build_deps(
                async_mongo_client=mongo,
                client_session=client_session,
                config=config,
            )
            deps.thread_id = DEMO_PIPELINE_THREAD_ID
            await run_demo_pipeline(
                limit=limit,
                username=config.DEMO_USERNAME,
                deps=deps,
                concurrency=config.PIPELINE_PAIR_CONCURRENCY,
            )
    finally:
        await mongo.close()
        if deps is not None:
            await deps.search_service.close()


def main() -> None:
    """CLI entrypoint for ``seed-demo-pipeline``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    asyncio.run(_async_main(args.limit))


if __name__ == "__main__":
    main()
