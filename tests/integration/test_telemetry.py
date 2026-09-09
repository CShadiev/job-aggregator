"""Integration tests for Prometheus metrics exposition, cost accounting, and instrumentation."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from prometheus_client.parser import text_string_to_metric_families
from pydantic_ai.usage import RunUsage
from pymongo import AsyncMongoClient

from config import ConfigProvider
from main import app
from monitoring.metrics import (
    JobStage,
    instrument_node,
    mark_node_failed,
    record_agent_usage,
    record_feed_query,
    record_job_stage,
    record_search_query,
)
from monitoring.pricing import DEFAULT_RATES, ModelRate, PricingCache

_PRICING_COLLECTION = "pricing_telemetry_test"


@pytest.fixture()
def client() -> TestClient:
    """Provide a FastAPI TestClient that does not re-raise server exceptions."""
    return TestClient(app, raise_server_exceptions=False)


def _sample_value(name: str, **labels: str) -> float:
    """Read a single sample from the default registry, treating absent series as zero."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _metric_names(exposition: str) -> set[str]:
    """Parse a Prometheus exposition payload into the set of metric family names."""
    return {family.name for family in text_string_to_metric_families(exposition)}


class TestMetricsEndpoint:
    """Tests for the /metrics scrape endpoint on the FastAPI application."""

    def test_metrics_endpoint_serves_prometheus_exposition(self, client: TestClient):
        """Verify /metrics responds with the Prometheus text exposition content type."""
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "# TYPE" in response.text

    def test_metrics_endpoint_exposes_declared_metric_families(self, client: TestClient):
        """Verify every metric family named in the observability plan is exported."""
        names = _metric_names(client.get("/metrics").text)

        assert {
            "llm_tokens",
            "llm_cost_estimated_usd",
            "llm_request_duration_seconds",
            "search_query_duration_seconds",
            "search_feed_query_duration_seconds",
            "search_queries",
            "search_hits_count",
            "pipeline_cycle_duration_seconds",
            "pipeline_node_duration_seconds",
            "pipeline_tasks",
            "job_descriptions",
            "mongo_checkpoint_duration_seconds",
            "http_requests",
            "http_request_duration_seconds",
        } <= names

    def test_http_requests_are_labelled_by_route_template(self, client: TestClient):
        """Verify request metrics use the route template so path params cannot explode cardinality."""
        before = _sample_value("http_requests_total", method="GET", path="/healthz", status="200")

        client.get("/healthz")

        after = _sample_value("http_requests_total", method="GET", path="/healthz", status="200")
        assert after == before + 1

    def test_metrics_endpoint_is_not_self_instrumented(self, client: TestClient):
        """Verify scraping does not inflate the HTTP counters with its own requests."""
        client.get("/metrics")
        before = _sample_value("http_requests_total", method="GET", path="/metrics", status="200")

        client.get("/metrics")

        assert (
            _sample_value("http_requests_total", method="GET", path="/metrics", status="200")
            == before
        )


class TestAgentUsageAccounting:
    """Tests for LLM token and estimated cost recording."""

    async def test_usage_increments_tokens_and_cost(self):
        """Verify record_agent_usage splits tokens by direction and prices them from the rate card."""
        model = "gpt-5-mini"
        rate = DEFAULT_RATES[model]
        prompt_before = _sample_value(
            "llm_tokens_total", agent="screening", model=model, type="prompt"
        )
        completion_before = _sample_value(
            "llm_tokens_total", agent="screening", model=model, type="completion"
        )
        cost_before = _sample_value("llm_cost_estimated_usd_total", agent="screening", model=model)

        await record_agent_usage(
            agent_name="screening",
            model_name=model,
            usage=RunUsage(input_tokens=1_000_000, output_tokens=500_000),
            duration_seconds=1.5,
        )

        assert (
            _sample_value("llm_tokens_total", agent="screening", model=model, type="prompt")
            == prompt_before + 1_000_000
        )
        assert (
            _sample_value("llm_tokens_total", agent="screening", model=model, type="completion")
            == completion_before + 500_000
        )
        expected_cost = rate.input_usd_per_1m + rate.output_usd_per_1m / 2
        assert _sample_value(
            "llm_cost_estimated_usd_total", agent="screening", model=model
        ) == pytest.approx(cost_before + expected_cost)
        assert (
            _sample_value("llm_request_duration_seconds_count", agent="screening", model=model) >= 1
        )

    async def test_unknown_model_is_recorded_at_zero_cost(self):
        """Verify an unpriced model still reports tokens rather than failing the agent run."""
        model = "model-nobody-priced"

        await record_agent_usage(
            agent_name="deduplication",
            model_name=model,
            usage=RunUsage(input_tokens=10, output_tokens=5),
            duration_seconds=0.1,
        )

        assert (
            _sample_value("llm_tokens_total", agent="deduplication", model=model, type="prompt")
            == 10
        )
        assert (
            _sample_value("llm_cost_estimated_usd_total", agent="deduplication", model=model) == 0.0
        )


class TestPricingCache:
    """Tests for the MongoDB-backed model rate card cache."""

    @pytest.fixture()
    async def pricing_collection(self) -> AsyncGenerator:
        """Provide a seeded pricing collection in the MongoDB test database."""
        config = ConfigProvider.get_config()
        mongo_client = AsyncMongoClient(
            host=config.MONGODB_HOST,
            port=config.MONGODB_PORT,
            username=config.MONGODB_USER,
            password=config.MONGODB_PASSWORD,
        )
        collection = mongo_client[config.MONGODB_TEST_DATABASE][_PRICING_COLLECTION]
        await collection.delete_many({})
        await collection.insert_one(
            {"model_name": "gpt-5-mini", "input_usd_per_1m": 9.0, "output_usd_per_1m": 99.0}
        )
        yield collection
        await collection.drop()
        await mongo_client.close()

    async def test_mongodb_rates_override_static_defaults(self, pricing_collection):
        """Verify a bound pricing collection takes precedence over the compiled-in defaults."""
        cache = PricingCache(ttl_seconds=300)
        cache.bind(pricing_collection)

        rate = await cache.get_rate("gpt-5-mini")

        assert rate == ModelRate(input_usd_per_1m=9.0, output_usd_per_1m=99.0)

    async def test_models_absent_from_mongodb_fall_back_to_defaults(self, pricing_collection):
        """Verify models missing from the collection still resolve through the static rate card."""
        cache = PricingCache(ttl_seconds=300)
        cache.bind(pricing_collection)

        assert await cache.get_rate("grok-4.3") == DEFAULT_RATES["grok-4.3"]

    async def test_unbound_cache_serves_defaults(self):
        """Verify a cache with no MongoDB binding still prices the known models."""
        cache = PricingCache(ttl_seconds=300)

        assert await cache.get_rate("gpt-5.6-luna") == DEFAULT_RATES["gpt-5.6-luna"]

    def test_cost_formula_is_per_million_tokens(self):
        """Verify estimated cost scales linearly per million tokens in each direction."""
        cache = PricingCache(ttl_seconds=300)
        rate = ModelRate(input_usd_per_1m=2.0, output_usd_per_1m=8.0)

        assert cache.estimate_cost_usd(rate, 500_000, 250_000) == pytest.approx(1.0 + 2.0)


class TestSearchInstrumentation:
    """Tests for search and feed latency recording helpers."""

    def test_search_query_records_duration_count_and_hits(self):
        """Verify a corpus search updates its histogram, counter, and hit distribution."""
        duration_before = _sample_value(
            "search_query_duration_seconds_count", type="hybrid", status="success"
        )
        queries_before = _sample_value("search_queries_total", type="hybrid", status="success")
        hits_before = _sample_value("search_hits_count_count", type="hybrid")

        record_search_query(search_type="hybrid", duration_seconds=0.042, status="success", hits=12)

        assert (
            _sample_value("search_query_duration_seconds_count", type="hybrid", status="success")
            == duration_before + 1
        )
        assert (
            _sample_value("search_queries_total", type="hybrid", status="success")
            == queries_before + 1
        )
        assert _sample_value("search_hits_count_count", type="hybrid") == hits_before + 1

    def test_feed_query_counts_under_the_feed_search_type(self):
        """Verify feed searches land in their own histogram and share the search query counter."""
        feed_before = _sample_value("search_feed_query_duration_seconds_count", status="success")
        queries_before = _sample_value("search_queries_total", type="feed", status="success")

        record_feed_query(duration_seconds=0.09, status="success", hits=25)

        assert (
            _sample_value("search_feed_query_duration_seconds_count", status="success")
            == feed_before + 1
        )
        assert (
            _sample_value("search_queries_total", type="feed", status="success")
            == queries_before + 1
        )


class TestNodeInstrumentation:
    """Tests for LangGraph node duration and outcome recording."""

    async def test_successful_node_counts_as_success(self):
        """Verify a node that returns normally records a success task."""
        before = _sample_value("pipeline_tasks_total", node="collect", status="success")

        async def node(state: dict) -> dict:
            return state

        await instrument_node("collect", node)({})

        assert _sample_value("pipeline_tasks_total", node="collect", status="success") == before + 1
        assert _sample_value("pipeline_node_duration_seconds_count", node="collect") >= 1

    async def test_raising_node_counts_as_failure(self):
        """Verify an exception propagates and is recorded as a failed task."""
        before = _sample_value("pipeline_tasks_total", node="embed_jobs", status="failure")

        async def node(state: dict) -> dict:
            raise RuntimeError("bulk index rejected")

        with pytest.raises(RuntimeError):
            await instrument_node("embed_jobs", node)({})

        assert (
            _sample_value("pipeline_tasks_total", node="embed_jobs", status="failure") == before + 1
        )

    async def test_internally_handled_failure_counts_as_failure(self):
        """Verify pair nodes that swallow errors are still counted as failures via mark_node_failed."""
        success_before = _sample_value("pipeline_tasks_total", node="screen", status="success")
        failure_before = _sample_value("pipeline_tasks_total", node="screen", status="failure")

        async def node(state: dict) -> dict:
            mark_node_failed()
            return {"skipped_reason": "screen_error: boom"}

        await instrument_node("screen", node)({})

        assert _sample_value("pipeline_tasks_total", node="screen", status="success") == (
            success_before
        )
        assert (
            _sample_value("pipeline_tasks_total", node="screen", status="failure")
            == failure_before + 1
        )


class TestJobDescriptionsStageAccounting:
    """Tests for job descriptions stage tracking metrics."""

    def test_record_job_stage_all_stages(self):
        """Verify record_job_stage increments job_descriptions_total for all 4 stages and sources."""
        stages: list[JobStage] = ["collection", "retrieval", "screening", "assessment"]
        source = "test_source_stepstone"

        for stage in stages:
            before = _sample_value("job_descriptions_total", stage=stage, source=source)
            record_job_stage(stage=stage, source=source, count=1)
            after = _sample_value("job_descriptions_total", stage=stage, source=source)
            assert after == before + 1

    def test_record_job_stage_batch_increment(self):
        """Verify count parameter increments the counter by batch size."""
        before = _sample_value("job_descriptions_total", stage="collection", source="arbeitnow")
        record_job_stage(stage="collection", source="arbeitnow", count=25)
        after = _sample_value("job_descriptions_total", stage="collection", source="arbeitnow")
        assert after == before + 25

    def test_record_job_stage_source_fallback(self):
        """Verify empty or None source falls back safely to 'unknown'."""
        before = _sample_value("job_descriptions_total", stage="retrieval", source="unknown")
        record_job_stage(stage="retrieval", source="", count=2)
        after = _sample_value("job_descriptions_total", stage="retrieval", source="unknown")
        assert after == before + 2

    def test_record_job_stage_negative_ignored(self):
        """Verify negative counts are rejected without error."""
        before = _sample_value("job_descriptions_total", stage="screening", source="stepstone")
        record_job_stage(stage="screening", source="stepstone", count=-5)
        after = _sample_value("job_descriptions_total", stage="screening", source="stepstone")
        assert after == before

    async def test_collect_node_records_job_stage(self):
        """Verify collect batch node increments collection metrics per source."""
        from models.collection_service import CollectionResult
        from orchestration.nodes.batch import make_batch_nodes
        from orchestration.state import new_pipeline_state
        from tests.helpers.job_posting import make_job_posting

        deps = MagicMock()
        deps.repository = AsyncMock()
        deps.collection_service = AsyncMock()
        deps.thread_id = "t1"
        deps.pair_mode = "topk"
        deps.retrieval_k = 2

        p1 = make_job_posting(uid="u1", source="source_a")
        p2 = make_job_posting(uid="u2", source="source_b")
        p3 = make_job_posting(uid="u3", source="source_a")
        deps.collection_service.collect.return_value = CollectionResult(
            postings=[p1, p2, p3], invalid_entries=[]
        )

        before_a = _sample_value("job_descriptions_total", stage="collection", source="source_a")
        before_b = _sample_value("job_descriptions_total", stage="collection", source="source_b")

        nodes = make_batch_nodes(deps)
        await nodes["collect"](new_pipeline_state(cycle_id="c1"))

        assert (
            _sample_value("job_descriptions_total", stage="collection", source="source_a")
            == before_a + 2
        )
        assert (
            _sample_value("job_descriptions_total", stage="collection", source="source_b")
            == before_b + 1
        )

    async def test_build_pairs_node_records_retrieval_metrics(self):
        """Verify build_pairs batch node increments retrieval metrics per source."""
        from orchestration.nodes.batch import make_batch_nodes
        from orchestration.state import new_pipeline_state

        deps = MagicMock()
        deps.repository = AsyncMock()
        profile_mock = MagicMock()
        profile_mock.username = "user1"
        deps.repository.get_user_profiles.return_value = [profile_mock]
        deps.pair_mode = "cartesian"

        nodes = make_batch_nodes(deps)
        jobs = [
            {"uid": "j1", "source": "src_x"},
            {"uid": "j2", "source": "src_x"},
            {"uid": "j3", "source": "src_y"},
        ]

        before_x = _sample_value("job_descriptions_total", stage="retrieval", source="src_x")
        before_y = _sample_value("job_descriptions_total", stage="retrieval", source="src_y")

        await nodes["build_pairs"](new_pipeline_state(cycle_id="c2", unique_jobs=jobs))

        assert (
            _sample_value("job_descriptions_total", stage="retrieval", source="src_x")
            == before_x + 2
        )
        assert (
            _sample_value("job_descriptions_total", stage="retrieval", source="src_y")
            == before_y + 1
        )

    async def test_pair_nodes_screen_and_assess_record_metrics(self):
        """Verify screen and assess pair nodes record screening and assessment metrics."""
        from models.fit_assessment import FitAssessment
        from models.screening import ScreeningResult
        from orchestration.nodes.pair import make_pair_nodes
        from orchestration.state import new_pair_state
        from tests.helpers.job_posting import make_job_posting

        deps = MagicMock()
        deps.repository = AsyncMock()
        deps.repository.get_screening.return_value = None
        deps.repository.get_assessment.return_value = None
        deps.repository.get_user_profile.return_value = MagicMock()
        deps.object_storage = MagicMock()
        deps.object_storage.get_user_cv.return_value = "Sample CV text"
        deps.screening_agent = AsyncMock()
        deps.screening_agent.screen.return_value = ScreeningResult(
            worth_full_assessment=True, confidence=0.9
        )
        deps.fit_assessment_agent = AsyncMock()
        deps.fit_assessment_agent.assess.return_value = FitAssessment(
            cv_ats_match_score=85.0,
            profile_ats_match_score=80.0,
            summary="Strong fit",
        )
        deps.screening_model = "test-model"
        deps.thread_id = "t1"
        deps.cover_letter_min_cv_score = 80

        posting = make_job_posting(uid="job_pair_1", source="source_pair_test")
        state = new_pair_state(
            cycle_id="c3",
            username="candidate1",
            job=posting.model_dump(mode="json"),
        )

        nodes = make_pair_nodes(deps)

        before_screen = _sample_value(
            "job_descriptions_total", stage="screening", source="source_pair_test"
        )
        await nodes["screen"](state)
        assert (
            _sample_value("job_descriptions_total", stage="screening", source="source_pair_test")
            == before_screen + 1
        )

        before_assess = _sample_value(
            "job_descriptions_total", stage="assessment", source="source_pair_test"
        )
        await nodes["assess"](state)
        assert (
            _sample_value("job_descriptions_total", stage="assessment", source="source_pair_test")
            == before_assess + 1
        )
