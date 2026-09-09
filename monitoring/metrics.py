"""Prometheus metric definitions and recording helpers.

Both the FastAPI process and the LangGraph pipeline runner import this module and
publish the same default registry — the API over ``GET /metrics``, the runner over a
standalone HTTP server started by :func:`start_worker_metrics_server`.

Every recording helper swallows its own errors: telemetry must never be able to fail
a search query, an agent run, or a pipeline node.
"""

from __future__ import annotations

import contextvars
import inspect
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import start_http_server as _start_http_server

from logger_provider import LoggerProvider
from monitoring.pricing import get_pricing_cache

if TYPE_CHECKING:
    from pydantic_ai.usage import RunUsage

log = LoggerProvider.get_logger()

AgentName = Literal["screening", "fit_assessment", "cover_letter", "deduplication"]
SearchType = Literal["hybrid", "bm25", "knn", "feed"]
Status = Literal["success", "error"]
TaskStatus = Literal["success", "failure"]
JobStage = Literal["collection", "retrieval", "screening", "assessment"]

# --- LLM & cost -----------------------------------------------------------------

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Tokens processed by LLM agents.",
    ["agent", "model", "type"],
)

llm_cost_estimated_usd_total = Counter(
    "llm_cost_estimated_usd_total",
    "Estimated LLM spend in USD derived from token counts and the model rate card.",
    ["agent", "model"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "Latency of individual LLM agent calls.",
    ["agent", "model"],
    buckets=(0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# --- Search & product -----------------------------------------------------------

search_query_duration_seconds = Histogram(
    "search_query_duration_seconds",
    "Latency of jobs corpus searches against OpenSearch.",
    ["type", "status"],
    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0, 2.0),
)

search_feed_query_duration_seconds = Histogram(
    "search_feed_query_duration_seconds",
    "Latency of candidate assessed-feed searches.",
    ["status"],
    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0),
)

search_queries_total = Counter(
    "search_queries_total",
    "Search queries handled, by mode and outcome.",
    ["type", "status"],
)

search_hits_count = Histogram(
    "search_hits_count",
    "Distribution of hit counts returned by search queries.",
    ["type"],
    buckets=(0, 1, 5, 10, 20, 50, 100, 250, 500),
)

# --- Pipeline & system health ---------------------------------------------------

pipeline_cycle_duration_seconds = Histogram(
    "pipeline_cycle_duration_seconds",
    "End-to-end duration of a batch pipeline cycle.",
    ["status"],
    buckets=(5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

pipeline_node_duration_seconds = Histogram(
    "pipeline_node_duration_seconds",
    "Execution time of individual LangGraph nodes.",
    ["node"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

pipeline_tasks_total = Counter(
    "pipeline_tasks_total",
    "Batch and pair tasks processed, by node and outcome.",
    ["node", "status"],
)

job_descriptions_total = Counter(
    "job_descriptions_total",
    "Job descriptions processed through each pipeline stage, by stage and source.",
    ["stage", "source"],
)

mongo_checkpoint_duration_seconds = Histogram(
    "mongo_checkpoint_duration_seconds",
    "Duration of LangGraph MongoDB checkpoint writes.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

dependency_up = Gauge(
    "dependency_up",
    "Reachability of a backing service as last observed by the readiness probe.",
    ["dependency"],
)

# --- HTTP -----------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests handled by the API, by route template and status code.",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Latency of HTTP requests handled by the API.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


def render_latest() -> tuple[bytes, str]:
    """Render the default registry in Prometheus exposition format with its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def start_worker_metrics_server(port: int, addr: str = "0.0.0.0") -> None:
    """Start the background metrics HTTP server used by the pipeline runner process."""
    _start_http_server(port, addr)
    log.info(
        "Worker metrics endpoint listening on {addr}:{port}/metrics",
        event="metrics_server_started",
        addr=addr,
        port=port,
    )


async def record_agent_usage(
    agent_name: AgentName,
    model_name: str,
    usage: RunUsage,
    duration_seconds: float,
) -> None:
    """Record tokens, estimated USD cost, and latency for a single agent LLM call.

    Args:
        agent_name: Logical agent label (``screening``, ``fit_assessment``, ...).
        model_name: Model identifier as reported by the PydanticAI model.
        usage: ``RunUsage`` returned by ``AgentRunResult.usage()``.
        duration_seconds: Wall-clock duration of the ``agent.run`` call.
    """
    try:
        input_tokens = int(usage.input_tokens or 0)
        output_tokens = int(usage.output_tokens or 0)
        rate = await get_pricing_cache().get_rate(model_name)
        cost = get_pricing_cache().estimate_cost_usd(rate, input_tokens, output_tokens)

        llm_tokens_total.labels(agent=agent_name, model=model_name, type="prompt").inc(input_tokens)
        llm_tokens_total.labels(agent=agent_name, model=model_name, type="completion").inc(
            output_tokens
        )
        llm_cost_estimated_usd_total.labels(agent=agent_name, model=model_name).inc(cost)
        llm_request_duration_seconds.labels(agent=agent_name, model=model_name).observe(
            duration_seconds
        )
    except Exception as exc:
        log.warning(
            "Failed to record LLM usage for {agent}/{model}: {exc}",
            event="metrics_record_failed",
            agent=agent_name,
            model=model_name,
            exc=str(exc),
        )


def record_search_query(
    *,
    search_type: SearchType,
    duration_seconds: float,
    status: Status,
    hits: int | None = None,
) -> None:
    """Record duration, outcome, and hit count of a jobs corpus search."""
    try:
        search_query_duration_seconds.labels(type=search_type, status=status).observe(
            duration_seconds
        )
        search_queries_total.labels(type=search_type, status=status).inc()
        if hits is not None:
            search_hits_count.labels(type=search_type).observe(hits)
    except Exception as exc:
        log.warning("Failed to record search metrics: {exc}", exc=str(exc))


def record_feed_query(
    *,
    duration_seconds: float,
    status: Status,
    hits: int | None = None,
) -> None:
    """Record duration, outcome, and hit count of a candidate assessed-feed search."""
    try:
        search_feed_query_duration_seconds.labels(status=status).observe(duration_seconds)
        search_queries_total.labels(type="feed", status=status).inc()
        if hits is not None:
            search_hits_count.labels(type="feed").observe(hits)
    except Exception as exc:
        log.warning("Failed to record feed metrics: {exc}", exc=str(exc))


def record_dependency_health(*, dependency: str, healthy: bool) -> None:
    """Publish the reachability of a backing service such as MongoDB or OpenSearch."""
    try:
        dependency_up.labels(dependency=dependency).set(1 if healthy else 0)
    except Exception as exc:
        log.warning("Failed to record dependency health: {exc}", exc=str(exc))


def record_pipeline_cycle(*, duration_seconds: float, status: Status) -> None:
    """Record the duration and outcome of one end-to-end pipeline cycle."""
    try:
        pipeline_cycle_duration_seconds.labels(status=status).observe(duration_seconds)
    except Exception as exc:
        log.warning("Failed to record pipeline cycle metrics: {exc}", exc=str(exc))


def record_job_stage(
    stage: JobStage,
    source: str = "unknown",
    count: int = 1,
) -> None:
    """Record job descriptions moving through a pipeline stage.

    Args:
        stage: Pipeline stage (``collection``, ``retrieval``, ``screening``, ``assessment``).
        source: Origin data source (e.g. ``"arbeitnow"``, ``"stepstone"``).
        count: Number of job descriptions to increment (defaults to 1).
    """
    try:
        if count < 0:
            log.warning("Negative count passed to record_job_stage: {count}", count=count)
            return
        if count == 0:
            return
        source_label = str(source).strip() if source and str(source).strip() else "unknown"
        job_descriptions_total.labels(stage=stage, source=source_label).inc(count)
    except Exception as exc:
        log.warning(
            "Failed to record job stage metric for {stage}/{source}: {exc}",
            stage=stage,
            source=source,
            exc=str(exc),
        )


record_job_descriptions = record_job_stage


def record_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record an HTTP request against the route-template path label."""
    try:
        http_requests_total.labels(method=method, path=path, status=str(status_code)).inc()
        http_request_duration_seconds.labels(method=method, path=path).observe(duration_seconds)
    except Exception as exc:
        log.warning("Failed to record HTTP metrics: {exc}", exc=str(exc))


_node_failed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "pipeline_node_failed", default=False
)


def mark_node_failed() -> None:
    """Flag the running node as failed when it handles the error instead of raising.

    Pair nodes funnel exceptions through their own failure handler and return a skip
    reason, so :func:`instrument_node` cannot see the failure from a raised exception.
    """
    _node_failed.set(True)


def instrument_node[StateT, ResultT](
    node: str,
    fn: Callable[[StateT], Awaitable[ResultT]],
) -> Callable[[StateT], Awaitable[ResultT]]:
    """Wrap a LangGraph node so every invocation records its duration and outcome.

    A raised exception counts as a failure, as does a node that called
    :func:`mark_node_failed` before returning.
    """

    async def instrumented(state: StateT) -> ResultT:
        token = _node_failed.set(False)
        start = perf_counter()
        status: TaskStatus = "success"
        try:
            return await fn(state)
        except Exception:
            status = "failure"
            raise
        finally:
            if _node_failed.get():
                status = "failure"
            _node_failed.reset(token)
            _record_pipeline_node(node=node, duration_seconds=perf_counter() - start, status=status)

    instrumented.__name__ = getattr(fn, "__name__", node)
    instrumented.__doc__ = fn.__doc__
    return instrumented


def _record_pipeline_node(*, node: str, duration_seconds: float, status: TaskStatus) -> None:
    """Record duration and outcome for one node invocation."""
    try:
        pipeline_node_duration_seconds.labels(node=node).observe(duration_seconds)
        pipeline_tasks_total.labels(node=node, status=status).inc()
    except Exception as exc:
        log.warning("Failed to record pipeline node metrics: {exc}", exc=str(exc))


def instrument_nodes(nodes: dict[str, Any]) -> dict[str, Any]:
    """Wrap every coroutine node in a node-factory mapping with :func:`instrument_node`.

    Routing helpers and other synchronous entries in the mapping are returned as-is.
    """
    return {
        name: instrument_node(name, fn) if inspect.iscoroutinefunction(fn) else fn
        for name, fn in nodes.items()
    }
