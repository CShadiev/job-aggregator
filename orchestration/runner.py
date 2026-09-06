"""Entrypoint for the LangGraph job pipeline schedule loop."""

import asyncio
import time
from uuid import uuid4

from aiohttp import ClientSession
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import AsyncMongoClient, MongoClient

from config import ConfigProvider
from logger_provider import LoggerProvider
from orchestration.deps import PipelineDeps, build_deps
from orchestration.graph import build_pipeline_graph
from orchestration.state import new_pipeline_state
from telemetry import cycle_id_ctx, get_tracer, setup_telemetry

log = LoggerProvider.get_logger()
tracer = get_tracer("job-aggregator.pipeline")


def _sync_mongo_client(config) -> MongoClient:
    return MongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )


async def run_once(
    *,
    graph,
    config,
) -> None:
    invoke_config = {
        "configurable": {"thread_id": config.PIPELINE_THREAD_ID},
        "max_concurrency": config.PIPELINE_PAIR_CONCURRENCY,
    }
    cycle_id = str(uuid4())
    token = cycle_id_ctx.set(cycle_id)
    try:
        with tracer.start_as_current_span("pipeline.cycle") as span:
            span.set_attribute("pipeline.cycle_id", cycle_id)
            span.set_attribute("pipeline.thread_id", config.PIPELINE_THREAD_ID)
            log.info(
                "Starting pipeline cycle",
                event="pipeline_cycle_start",
                cycle_id=cycle_id,
                thread_id=config.PIPELINE_THREAD_ID,
            )
            await graph.ainvoke(new_pipeline_state(cycle_id=cycle_id), config=invoke_config)
            log.info(
                "Pipeline cycle finished",
                event="pipeline_cycle_end",
                cycle_id=cycle_id,
                thread_id=config.PIPELINE_THREAD_ID,
            )
    finally:
        cycle_id_ctx.reset(token)


async def _async_main() -> None:
    config = ConfigProvider.get_config()
    setup_telemetry()
    async_mongo = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    sync_mongo = _sync_mongo_client(config)
    checkpointer = MongoDBSaver(
        sync_mongo,
        db_name=config.MONGODB_DATABASE,
        checkpoint_collection_name=config.MONGODB_LANGGRAPH_CHECKPOINT_COLLECTION,
        writes_collection_name=config.MONGODB_LANGGRAPH_WRITES_COLLECTION,
    )

    deps: PipelineDeps | None = None
    try:
        async with ClientSession() as client_session:
            deps = await build_deps(
                async_mongo_client=async_mongo,
                client_session=client_session,
                config=config,
            )
            await deps.repository.ensure_pipeline_indexes()
            await deps.search_service.ensure_indices()
            graph = build_pipeline_graph(deps, checkpointer)
            await run_once(graph=graph, config=config)
    finally:
        await async_mongo.close()
        sync_mongo.close()
        if deps is not None:
            await deps.search_service.close()


def main() -> None:
    config = ConfigProvider.get_config()
    log.info(
        "{service}: Starting LangGraph pipeline",
        service="pipeline_runner",
        event="started",
        success=1,
        thread_id=config.PIPELINE_THREAD_ID,
    )
    try:
        while True:
            asyncio.run(_async_main())
            time.sleep(config.PIPELINE_SCHEDULE_SECONDS)
    except Exception:
        log.exception(
            "{service}: Error in LangGraph pipeline",
            service="pipeline_runner",
            event="error",
            success=0,
            exc_info=True,
        )
        raise


if __name__ == "__main__":
    main()
