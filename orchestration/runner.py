"""Entrypoint for the LangGraph job pipeline schedule loop."""

import asyncio
import time
from time import perf_counter
from uuid import uuid4

from aiohttp import ClientSession
from pymongo import AsyncMongoClient, MongoClient

from config import ConfigProvider
from logger_provider import LoggerProvider
from monitoring.metrics import record_pipeline_cycle, start_worker_metrics_server
from monitoring.pricing import configure_pricing
from orchestration.checkpointer import InstrumentedMongoDBSaver
from orchestration.deps import PipelineDeps, build_deps
from orchestration.graph import build_pipeline_graph
from orchestration.state import new_pipeline_state
from telemetry import configure_langsmith, cycle_id_ctx, get_tracer, setup_telemetry

log = LoggerProvider.get_logger()
tracer = get_tracer("job-aggregator.pipeline")


def _sync_mongo_client(config) -> MongoClient:
    """Instantiate a synchronous MongoClient used by LangGraph checkpointer."""
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
    """Execute a single end-to-end pipeline run over the compiled graph."""
    invoke_config = {
        "configurable": {"thread_id": config.PIPELINE_THREAD_ID},
        "max_concurrency": config.PIPELINE_PAIR_CONCURRENCY,
    }
    cycle_id = str(uuid4())
    token = cycle_id_ctx.set(cycle_id)
    start = perf_counter()
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
            try:
                await graph.ainvoke(new_pipeline_state(cycle_id=cycle_id), config=invoke_config)
            except Exception:
                record_pipeline_cycle(duration_seconds=perf_counter() - start, status="error")
                raise
            record_pipeline_cycle(duration_seconds=perf_counter() - start, status="success")
            log.info(
                "Pipeline cycle finished",
                event="pipeline_cycle_end",
                cycle_id=cycle_id,
                thread_id=config.PIPELINE_THREAD_ID,
            )
    finally:
        cycle_id_ctx.reset(token)


async def _async_main() -> None:
    """Async orchestration entrypoint initializing dependencies and triggering a single run."""
    config = ConfigProvider.get_config()
    setup_telemetry()
    log.info(
        "LangSmith tracing {status}",
        event="langsmith_configured",
        status="enabled" if configure_langsmith() else "disabled",
        project=config.LANGSMITH_PROJECT,
    )
    async_mongo = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    sync_mongo = _sync_mongo_client(config)
    configure_pricing(async_mongo, config=config)
    checkpointer = InstrumentedMongoDBSaver(
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
    """Top-level CLI entrypoint running the orchestration scheduler loop."""
    config = ConfigProvider.get_config()
    if config.METRICS_ENABLED:
        start_worker_metrics_server(config.WORKER_METRICS_PORT, config.WORKER_METRICS_HOST)
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
