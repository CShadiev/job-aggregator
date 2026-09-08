# Observability, Cost Accounting & Dashboards — Implementation Plan

**Status:** Implemented  
**Last updated:** 2026-09-08  
**Open questions:** 0  
**Origin:** Extracted from [Epic 3 (Section C)](./archive/epic-03-rag-assistant-observability.md) following completion of [Epic 2 (Hybrid Search)](./archive/epic-02-hybrid-search-retrieval-eval.md)

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done).

---

## Problem

With the completion of Epic 2 (Hybrid Search & Retrieval Evaluation), the job aggregator executes multi-agent LLM pipelines (`ScreeningAgent`, `FitAssessmentAgent`, `CoverLetterGenerationAgent`, `DeduplicationAgent`), embeds postings into OpenSearch dense vector indices, and serves hybrid BM25 + k-NN assessed job feeds.

However, the operational and financial characteristics of the system are currently opaque:
1. **Zero LLM Token & Financial Observability:** LLM calls through PydanticAI models (`gpt-5.6-luna`, `gpt-5-mini`, `grok-4.3`, etc.) execute without aggregate tracking of prompt tokens, completion tokens, or estimated USD expenditures. Budget burn rates cannot be audited or budgeted.
2. **Search Latency & Throughput Blindness:** OpenSearch query durations (`bm25`, `knn`, `hybrid` RRF fusion) and candidate assessed feed query latencies are emitted only as local trace spans (`search/search_service.py:173`), lacking timeseries aggregation, QPS metrics, and percentile latency percentiles (p50, p95, p99).
3. **Pipeline Health & Node Failure Tracking:** LangGraph pipeline runs across batch and candidate-job pair subgraphs (`orchestration/nodes/batch.py`, `orchestration/nodes/pair.py`) log errors to MongoDB `failed_tasks` but lack real-time visibility into node execution times, checkpoint write latencies (`MongoDBSaver`), and error budget depletion.
4. **No Unified Monitoring Interface:** Developers and operators currently have no dashboard view into system health or SLO compliance.

To maintain engineering momentum within time constraints, conversational RAG chat and cloud canary packaging (Epics 3A/3B/3D and Epic 4) are deferred. This implementation plan focuses entirely on delivering a production-grade, reproducible **Observability, Cost Accounting & Dashboards** stack for the core search engine and multi-agent pipeline.

---

## Scope

### In scope

- **Prometheus Metrics Engine & Exporters:**
  - Exporting Prometheus metrics from FastAPI web service (`main.py`) via `/metrics`.
  - Exporting Prometheus metrics from scheduled/background LangGraph pipeline runner (`orchestration/runner.py`).
  - Standardized metric definitions for LLM token usage, estimated USD costs, search query durations, pipeline node latencies, and task error counts.
- **Granular LLM Cost & Token Telemetry:**
  - Capturing PydanticAI `RunUsage` (`input_tokens`, `output_tokens`, `total_tokens`) across all agents (`ScreeningAgent`, `FitAssessmentAgent`, `CoverLetterGenerationAgent`, `DeduplicationAgent`) via direct `record_agent_usage` hook.
  - Real-time estimated USD cost computation backed by a dynamic MongoDB `pricing` collection with in-memory caching and fallback defaults.
  - Metrics labeled by agent name, model identifier, and token direction (`prompt` vs. `completion`).
- **Search & Pipeline Health Instrumentation:**
  - Instrumentation of OpenSearch operations in `SearchService` (query duration by search mode `hybrid|bm25|knn|feed`, result counts).
  - Instrumentation of LangGraph cycle and node durations (`collect`, `normalize`, `deduplicate`, `persist`, `build_pairs`, `embed_jobs`, `finalize`, `screen`, `assess`, `generate_cover_letter`).
  - Tracking of task execution success vs. failure rates and MongoDB checkpoint latency.
- **Local Observability Stack in `docker-compose.yml`:**
  - Containerized **Grafana Alloy** telemetry collector configured to scrape Prometheus endpoints from API and worker services.
  - Forwarding pipeline in Alloy using `prometheus.remote_write` to stream metrics to the Prometheus TSDB (or Grafana Cloud).
  - Containerized Prometheus instance with remote-write receiver enabled and alerting rule evaluation.
  - Containerized Grafana instance with automated provisioning (datasources and dashboards as code).
  - Forward-compatible architecture: Alloy provides the foundation to ingest OTel traces (for Tempo) and Loguru logs (for Loki) in future phases without altering application metrics endpoints.
- **Grafana Dashboards as Code (3 Core Views):**
  1. **LLM Cost & Token Accounting Dashboard:** Visualizing cumulative and per-cycle token consumption, USD spend breakdown by agent, cost per candidate/cycle, and burn rate.
  2. **Product & Search Performance Dashboard:** Visualizing query throughput (QPS), p50/p95/p99 search latency, distribution by search mode (`hybrid`, `bm25`, `knn`, `feed`), and RRF score distributions.
  3. **Pipeline & System Health Dashboard:** Visualizing LangGraph node execution durations, error budget depletion, failure counts by node/task, and MongoDB/OpenSearch connectivity status.
- **SLO Definitions & Alert Rules:**
  - Codified Prometheus alerting rules for Search Latency SLO (95% < 150ms), Assessed Feed Latency SLO (95% < 200ms), and Pipeline Error Budget (< 0.5% task failure rate).
- **Automated CI Metrics Verification:**
  - Automated integration test suite validating `/metrics` exposition and registry counter/histogram increments; dashboard panel validation against real application workflow execution.

### Out of scope

- Conversational RAG assistant service (`POST /rag/query`), citation parser, streaming tokens, and chat frontend (deferred from Epic 3A/3D).
- RAG ground-truth evaluation benchmark suite (deferred from Epic 3B).
- Cloud Kubernetes deployment, Terraform IaC, and Argo Rollouts progressive canary delivery (deferred from Epic 4).
- Production multi-tenant billing or payment gateway integrations (internal cost estimation only).
- Standalone synthetic traffic generator script (deferred in favor of validating against real staging/production workloads and CI integration tests).

---

## Codebase grounding

What already exists in the repository that this feature touches, reuses, or strains:

| Area | Location | What it means for this feature |
| --- | --- | --- |
| **Telemetry & Tracing** | `telemetry.py:35` | Initializes OpenTelemetry `TracerProvider`, trace contextvars (`request_id_ctx`, `cycle_id_ctx`), and instrumentors for FastAPI, PyMongo, HTTPX, and AioHTTP. Provides the baseline tracing infrastructure to coordinate with metrics. |
| **Application Entrypoint** | `main.py:77-85` | FastAPI application bootstrap, middleware configuration, and router registration. Needs Prometheus `/metrics` endpoint mounted and instrumented. |
| **Pipeline Runner** | `orchestration/runner.py:32-125` | Standalone CLI entrypoint (`run-pipeline`) running the schedule loop over LangGraph. Runs in a separate process from FastAPI, requiring a dedicated metrics export strategy. |
| **Batch Nodes** | `orchestration/nodes/batch.py:23-280` | LangGraph nodes for `collect`, `normalize`, `deduplicate`, `persist`, `build_pairs`, `embed_jobs`, and `finalize`. Node durations and error counts must be instrumented here. |
| **Pair Subgraph Nodes** | `orchestration/nodes/pair.py:19-180` | Parallel pair execution nodes (`screen`, `assess`, `generate_cover_letter`) and failure handler (`_fail_pair` writing to `failed_tasks`). Granular error and timing metrics attach here. |
| **Screening Agent** | `agents/screening.py:38-45` | Executes PydanticAI `self.agent.run(user_content)`. Yields `result.usage()` containing input and output token counts. |
| **Fit Assessment Agent** | `agents/fit_assessment.py:58-61` | Executes PydanticAI `self.agent.run(user_content)`. Token counts need extraction and cost assignment. |
| **Cover Letter Agent** | `agents/cover_letter_generation.py:52-54` | Executes PydanticAI `self.agent.run(prompt)`. Token counts need extraction and cost assignment. |
| **Deduplication Agent** | `agents/deduplication.py:73-77` | Executes batch normalization via PydanticAI `self.agent.run(prompt)`. Token counts need extraction and cost assignment. |
| **Model Registry** | `agents/model_factory.py:18-40` | Enumerates models (`grok-4.3`, `gpt-5.6-luna`, `gpt-5-mini`). Central registry for mapping model names to pricing tiers. |
| **Dynamic Rate Cards** | `monitoring/pricing.py` | *New component.* Queries MongoDB `pricing` collection for token rates with in-memory TTL caching and static defaults. |
| **Search Service** | `search/search_service.py:154-222` | Houses `search_jobs` (`bm25`, `knn`, `hybrid`) and `search_user_feed`. Already creates OTel spans; needs Prometheus latency histograms by search mode. |
| **Telemetry Collector** | `monitoring/alloy/config.alloy` | *New component.* Declarative Grafana Alloy pipeline configured for `prometheus.scrape` of API and worker, forwarding via `prometheus.remote_write`. |
| **Local Services** | `docker-compose.yml:1-92` | Defines local containers (`mongodb`, `opensearch`, `opensearch-dashboards`, `api`). Must be extended with `alloy`, `prometheus`, and `grafana` services. |
| **Application Config** | `config.py:15-130` | Pydantic Settings management. Requires new configuration keys for Prometheus ports, metrics toggle, and model pricing parameters. |

---

## Design

### Architecture & Telemetry Pipeline

```
┌────────────────────────────────────────────────────────────────────────┐
│ FastAPI Application (:8000)                                           │
│  ├── /jobs/search ──────> search_query_duration_seconds{type=...}      │
│  ├── /readyz, /healthz                                                 │
│  └── /metrics ──────────> Prometheus HTTP Scrape Endpoint              │
└──────────────────────────────────▲─────────────────────────────────────┘
                                   │
                                   │ HTTP scrape :8000/metrics
┌──────────────────────────────────┴─────────────────────────────────────┐
│ Grafana Alloy Telemetry Collector (:12345)                             │
│  ├── Component: prometheus.scrape "app_metrics"                        │
│  │     └── Scrapes :8000/metrics (API) & :8001/metrics (Worker)        │
│  ├── Component: prometheus.remote_write "tsdb_sink"                    │
│  │     └── Streams timeseries to Prometheus (:9090) or Grafana Cloud   │
│  └── (Future: otelcol.receiver.otlp for Tempo & loki.source for Loki)  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ prometheus.remote_write
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Prometheus Server (:9090) / Grafana Cloud Mimir                        │
│  ├── TSDB receiver stores metrics timeseries                           │
│  └── Evaluates Alerts & Recording Rules (SLO 1 & SLO 2)                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ queries PromQL
┌──────────────────────────────────▼─────────────────────────────────────┐
│ Grafana Dashboards (:3000)                                             │
│  ├── 1. LLM Cost & Token Accounting                                    │
│  ├── 2. Product & Search Performance                                   │
│  └── 3. Pipeline & System Health                                       │
└────────────────────────────────────────────────────────────────────────┘
                                   ▲
                                   │ HTTP scrape :8001/metrics
┌──────────────────────────────────┴─────────────────────────────────────┐
│ LangGraph Pipeline Runner (:8001)                                      │
│  ├── Background metrics HTTP daemon (prometheus_client) on :8001       │
│  ├── Agents (Screening, Fit, CoverLetter, Dedupe)                      │
│  │     └── captures result.usage() ──> llm_tokens_total                │
│  │                                 ──> llm_cost_estimated_usd_total    │
│  ├── Batch Nodes (collect, dedupe, embed, pairs)                       │
│  │     └── pipeline_cycle_duration_seconds, pipeline_tasks_total       │
│  └── Checkpointer (MongoDBSaver write latency)                         │
└────────────────────────────────────────────────────────────────────────┘
```

### Metrics Schema & Exporters

The metrics suite adheres to standard Prometheus naming conventions, exposed via `prometheus-client`.

#### 1. LLM & Cost Metrics
- **`llm_tokens_total`** (Counter):
  - Description: Total tokens processed by LLM agents.
  - Labels: `agent` (`screening`, `fit_assessment`, `cover_letter`, `deduplication`), `model` (`gpt-5.6-luna`, `gpt-5-mini`, etc.), `type` (`prompt`, `completion`).
- **`llm_cost_estimated_usd_total`** (Counter):
  - Description: Cumulative estimated cost in USD based on token consumption and model rate card.
  - Labels: `agent`, `model`.
  - Calculation: Handled via helper `record_agent_usage(agent_name, model_name, usage, duration_seconds)`. Rates are fetched from `monitoring/pricing.py`, which looks up model rates from the MongoDB `pricing` collection (with in-memory TTL cache and static fallback defaults).
- **`llm_request_duration_seconds`** (Histogram):
  - Description: Execution latency of individual LLM agent calls.
  - Labels: `agent`, `model`.
  - Buckets: `[0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]`.

#### 2. Search & Product Metrics
- **`search_query_duration_seconds`** (Histogram):
  - Description: Latency of corpus search queries in OpenSearch.
  - Labels: `type` (`hybrid`, `bm25`, `knn`), `status` (`success`, `error`).
  - Buckets: `[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0, 2.0]`.
- **`search_feed_query_duration_seconds`** (Histogram):
  - Description: Latency of candidate assessed feed searches (`POST /jobs/search`).
  - Labels: `status` (`success`, `error`).
  - Buckets: `[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0]`.
- **`search_queries_total`** (Counter):
  - Description: Total number of search queries handled.
  - Labels: `type` (`hybrid`, `bm25`, `knn`, `feed`), `status` (`success`, `error`).
- **`search_hits_count`** (Histogram):
  - Description: Distribution of hit counts returned by search queries.
  - Labels: `type`.

#### 3. Pipeline & System Health Metrics
- **`pipeline_cycle_duration_seconds`** (Histogram):
  - Description: Total elapsed time for an end-to-end batch pipeline cycle.
  - Labels: `status` (`success`, `error`).
  - Buckets: `[5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0]`.
- **`pipeline_node_duration_seconds`** (Histogram):
  - Description: Execution time of individual LangGraph nodes.
  - Labels: `node` — the graph's own node names: `collect`, `normalize`, `dedupe`, `persist_jobs`, `embed_jobs`, `build_pairs`, `finalize`, `screen`, `assess`, `cover_letter`, `emit_pair_result`.
  - Buckets: `[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]`.
- **`pipeline_tasks_total`** (Counter):
  - Description: Total pair and batch tasks processed.
  - Labels: `node`, `status` (`success`, `failure`).
- **`mongo_checkpoint_duration_seconds`** (Histogram):
  - Description: Duration of Mongo checkpoint write operations by `MongoDBSaver`.
  - Buckets: `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]`.

### Dashboards as Code & Provisioning

All Grafana dashboards, datasources, and Alloy configurations are codified in the repository under `monitoring/`:

```
monitoring/
├── alloy/
│   └── config.alloy            # Alloy pipeline: prometheus.scrape -> prometheus.remote_write
├── prometheus/
│   ├── prometheus.yml          # Prometheus TSDB receiver & alert evaluation config
│   └── alert_rules.yml         # SLO alerting rules
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── prometheus.yml  # Auto-registers Prometheus default datasource
    │   └── dashboards/
    │       └── dashboards.yml  # Auto-provisions dashboards from json directory
    └── dashboards/
        ├── llm-cost-accounting.json
        ├── search-performance.json
        └── pipeline-system-health.json
```

#### Dashboard 1: LLM Cost & Token Accounting
- **Top Row KPI Gauges:** Estimated USD Spend (Last 24h), Total Tokens, Average Cost Per Cycle, Average Tokens Per Assessed Pair.
- **Spend Over Time (Graph):** Stacked bar / time series of USD spend broken down by agent (`screening`, `fit_assessment`, `cover_letter`, `deduplication`).
- **Token Split (Donut/Pie):** Prompt vs. Completion tokens per agent and model.
- **Model Efficiency Table:** Table summarizing total runs, input tokens, output tokens, total cost, and average latency per model.

#### Dashboard 2: Product & Search Performance
- **Top Row KPI Gauges:** Current Search QPS, p95 Search Latency, p95 Assessed Feed Latency, Search Error Rate.
- **Latency Distribution (Heatmap/Timeseries):** `search_query_duration_seconds` p50, p95, and p99 percentiles over time by mode (`hybrid`, `bm25`, `knn`), and `search_feed_query_duration_seconds` percentiles for candidate feed queries.
- **Throughput by Query Type (Timeseries):** Breakdown of traffic across hybrid, keyword-only, vector-only, and assessed feed queries.
- **SLO Gauges:** Compliance gauges for Search Latency SLO ($< 150\text{ms}$) and Assessed Feed Latency SLO ($< 200\text{ms}$) over a rolling 1-hour window.

#### Dashboard 3: Pipeline & System Health
- **Top Row KPI Gauges:** Pipeline Active Status, Last Cycle Duration, Task Success Rate (%), Failed Tasks Count.
- **Node Execution Times (Bar / Timeseries):** p95 latency for each LangGraph node (`embed_jobs`, `build_pairs`, `screen`, `assess`, etc.).
- **Task Failure Trend (Timeseries):** Failed tasks per node over time.
- **Checkpoint & Database Latency:** Mongo checkpoint write duration p95 and OpenSearch bulk indexing duration.

### SLO Definitions & Alert Rules

Prometheus alert rules evaluate against Prometheus recording metrics:
1. **SLO 1 — Search Latency (Corpus Retrieval):**
   - Objective: $\ge 95\%$ of search queries respond in $< 150\text{ms}$ over a 5-minute evaluation window.
   - PromQL:
     ```promql
     sum(rate(search_query_duration_seconds_bucket{le="0.15"}[5m]))
     /
     sum(rate(search_query_duration_seconds_count[5m])) < 0.95
     ```
   - Alert: `SearchLatencySLOBreach` (Severity: warning).
2. **SLO 2 — Assessed Feed Latency (Candidate Feeds):**
   - Objective: $\ge 95\%$ of assessed feed searches (`POST /jobs/search`) respond in $< 200\text{ms}$ over a 5-minute evaluation window.
   - PromQL:
     ```promql
     sum(rate(search_feed_query_duration_seconds_bucket{le="0.2"}[5m]))
     /
     sum(rate(search_feed_query_duration_seconds_count[5m])) < 0.95
     ```
   - Alert: `FeedLatencySLOBreach` (Severity: warning).
3. **SLO 3 — Pipeline Error Budget:**
   - Objective: Task failure rate must be $< 0.5\%$ per pipeline cycle.
   - PromQL:
     ```promql
     sum(rate(pipeline_tasks_total{status="failure"}[15m]))
     /
     sum(rate(pipeline_tasks_total[15m])) > 0.005
     ```
   - Alert: `PipelineErrorBudgetDepleted` (Severity: warning).

---

## Open questions

*None. All open questions resolved.*

---

## Decision log

### Q1 — Dual scrape targets collected via Grafana Alloy

**Decided:** 2026-09-08  
FastAPI exposes `/metrics` on port 8000, and `orchestration/runner.py` starts a background metrics HTTP server via `prometheus_client.start_http_server(port=8001)`. A dedicated Grafana Alloy container (`image: grafana/alloy`) acts as the unified collector, scraping `:8000/metrics` and `:8001/metrics` via its `prometheus.scrape` component, and streaming them via `prometheus.remote_write` to the local Prometheus TSDB (or Grafana Cloud).

**Rejected:**  
- *Direct Prometheus scraping without collector:* Lacks a unified egress pipeline for Grafana Cloud and would require re-architecting the collector topology when traces (Tempo) and logs (Loki) are introduced.
- *Pushgateway (Option B):* Adds an ephemeral push buffer container with edge-triggered staleness issues; unnecessary when the runner can easily serve a lightweight pull endpoint.
- *Shared volume multiprocess mode (Option C):* File-locking complexity across separate containers in Docker Compose.

**Consequence:** Adds `monitoring/alloy/config.alloy`, introduces `alloy` service in `docker-compose.yml`, configures Prometheus with `--web.enable-remote-write-receiver`, and updates Phase 1 and Phase 4.

### Q2 — Direct agent usage hook helper

**Decided:** 2026-09-08  
Implement `record_agent_usage(agent_name: str, model_name: str, usage: RunUsage, duration_seconds: float)` in `monitoring/metrics.py`. Call this helper directly after `await self.agent.run(...)` across all four agents (`ScreeningAgent`, `FitAssessmentAgent`, `CoverLetterGenerationAgent`, and `DeduplicationAgent`).

**Rejected:**  
- *Custom agent wrapper / decorator (Option B):* Introduces indirection, risks breaking or drifting across PydanticAI framework updates, and complicates type checking.
- *OpenTelemetry GenAI spans bridge (Option C):* Overly heavy, requires complex collector span-to-metric processors, and loses direct programmatic control over exact token cost multipliers.

**Consequence:** Clean, explicit hook in each agent without monkey-patching; unit tests can directly mock or assert `record_agent_usage`.

### Q3 — Dynamic MongoDB collection for model rate cards

**Decided:** 2026-09-08  
Store model pricing rate cards dynamically in a MongoDB `pricing` collection (`model_name`, `input_usd_per_1m`, `output_usd_per_1m`, `updated_at`). Implement `monitoring/pricing.py` to query MongoDB with an in-memory TTL cache (e.g. 5 minutes) and a static fallback dictionary of known models (`gpt-5.6-luna`, `gpt-5-mini`, `grok-4.3`, etc.).

**Rejected:**  
- *Code-level only (Option A):* Requires application code changes and deployment cycles whenever foundation model vendors update token prices.
- *Configuration settings in config.py (Option B):* Requires environment variable changes and container restarts across services to take effect.

**Consequence:** Pricing updates are dynamic and operational via MongoDB without downtime; offline or startup fallback defaults guarantee that cost telemetry never halts or crashes LLM agent execution.

### Q4 — Assessed Feed Latency replaces deferred RAG SLO

**Decided:** 2026-09-08  
Replace the deferred RAG TTFT SLO with Assessed Feed Latency SLO: $\ge 95\%$ of assessed candidate feed searches (`POST /jobs/search`) must respond in $< 200\text{ms}$ over a 5-minute rolling window.

**Rejected:**  
- *Batch Embedding Throughput (Option B):* Focuses on internal background worker throughput rather than candidate-facing responsiveness.
- *Omit SLO 2 (Option C):* Leaves the primary search feed endpoint without an operational latency objective.

**Consequence:** Codifies `FeedLatencySLOBreach` in `monitoring/prometheus/alert_rules.yml`, instruments `search_feed_query_duration_seconds`, and adds a feed SLO gauge to `search-performance.json`.

### Q5 — Verification via real production activity & CI integration tests

**Decided:** 2026-09-08  
Skip dedicated synthetic traffic generator scripts (`scripts/simulate_telemetry_traffic.py` / k6). Verify metrics flow and Grafana dashboards using real pipeline runs and application traffic in local/staging environments, coupled with an automated integration test in CI (`tests/integration/test_telemetry.py`) asserting `/metrics` outputs and label values.

**Rejected:**  
- *Standalone Python generator script (Option A):* Adds a bespoke script to maintain that quickly bit-rots compared to real workflow executions.
- *k6 load testing script & container (Option B):* Unnecessary container footprint and test maintenance overhead for local metric validation.

**Consequence:** Simplifies Phase 6 to focus on CI automated test suite (`tests/integration/test_telemetry.py`) and live operational smoke verification on active workloads.

---

## Suggested question sequence

*All questions have been deliberated and resolved. See Decision log above.*

---

## Implementation phases

### Phase 1 — Prometheus Metrics Engine & API Instrumentation

**Depends on:** Q1 (resolved)  
**Reviewable when:** `GET /metrics` on FastAPI returns standard Prometheus metrics format with process and HTTP metrics, and worker exposes `/metrics` on port 8001.  
**Touches:** `pyproject.toml`, `telemetry.py`, `main.py`, `api/middleware/`, `orchestration/runner.py`

- Add `prometheus-client` to `pyproject.toml`.
- Create `monitoring/metrics.py` defining Prometheus metrics singletons (`llm_tokens_total`, `llm_cost_estimated_usd_total`, `search_query_duration_seconds`, `search_feed_query_duration_seconds`, `pipeline_cycle_duration_seconds`, etc.).
- Mount `/metrics` endpoint on the FastAPI application in `main.py`.
- Add ASGI middleware to track HTTP request count and latency percentiles.
- Add background `prometheus_client.start_http_server(port=8001)` to `orchestration/runner.py`.

### Phase 2 — Agent LLM Token & Cost Accounting

**Depends on:** Q2 (resolved), Q3 (resolved)  
**Reviewable when:** Running any agent (`screening`, `fit_assessment`, `cover_letter`, `deduplication`) immediately increments `llm_tokens_total` and `llm_cost_estimated_usd_total` with correct labels.  
**Touches:** `agents/screening.py`, `agents/fit_assessment.py`, `agents/cover_letter_generation.py`, `agents/deduplication.py`, `monitoring/pricing.py`, `monitoring/metrics.py`

- Implement `monitoring/pricing.py` querying MongoDB `pricing` collection with in-memory TTL caching and static fallback rate defaults.
- Implement helper `record_agent_usage(agent_name, model_name, usage, duration_seconds)` in `monitoring/metrics.py`.
- Update each agent (`ScreeningAgent.screen`, `FitAssessmentAgent.assess`, `CoverLetterGenerationAgent.generate`, `DeduplicationAgent._process_batch`) to call `record_agent_usage` immediately after `await self.agent.run(...)`.
- Unit tests validating that token counts and dynamic cost calculations match expected formulas.

### Phase 3 — Search & LangGraph Pipeline Instrumentation

**Depends on:** Q1 (resolved)  
**Reviewable when:** Executing `SearchService` queries and running pipeline cycles populates search duration histograms and pipeline node timing metrics.  
**Touches:** `search/search_service.py`, `orchestration/nodes/batch.py`, `orchestration/nodes/pair.py`, `orchestration/runner.py`

- Instrument `search_jobs` and `search_user_feed` in `SearchService` to record `search_query_duration_seconds` (by mode: `hybrid`, `bm25`, `knn`) and `search_feed_query_duration_seconds`.
- Instrument batch and pair nodes in `orchestration/nodes/` to record execution duration and task outcome (`success` vs. `failure`).
- Instrument pipeline runner (`orchestration/runner.py`) to expose metrics on `:8001` and record cycle duration.

### Phase 4 — Local Observability Infrastructure with Grafana Alloy

**Depends on:** Q1 (resolved)  
**Reviewable when:** `docker compose up -d` boots `alloy`, `prometheus`, and `grafana`, Alloy successfully scrapes targets, and Grafana is accessible on `:3000`.  
**Touches:** `docker-compose.yml`, `monitoring/alloy/config.alloy`, `monitoring/prometheus/prometheus.yml`, `monitoring/grafana/provisioning/`

- Create `monitoring/alloy/config.alloy` declaring:
  - `prometheus.scrape "app_metrics"` targeting `job-aggregator-api:8000` and `job-aggregator-worker:8001`.
  - `prometheus.remote_write "tsdb_sink"` streaming to local Prometheus receiver (`http://prometheus:9090/api/v1/write`) or configurable Grafana Cloud endpoints.
- Add `alloy` service (`image: grafana/alloy:latest`) to `docker-compose.yml`.
- Add `prometheus` service to `docker-compose.yml` with `--web.enable-remote-write-receiver` for local TSDB metrics ingestion and alert evaluation.
- Add `grafana` service to `docker-compose.yml` with pre-configured Prometheus datasource provisioning.
- Enable anonymous authentication for local Grafana development.

### Phase 5 — Grafana Dashboards as Code & Alert Rules

**Depends on:** Q4 (resolved)  
**Reviewable when:** Opening Grafana shows 3 fully configured dashboards (`LLM Cost & Token Accounting`, `Product & Search Performance`, `Pipeline & System Health`) with active alert rules.  
**Touches:** `monitoring/grafana/dashboards/*.json`, `monitoring/prometheus/alert_rules.yml`

- Codify `llm-cost-accounting.json` with token burn rates, agent cost breakdown, and per-user/cycle spending.
- Codify `search-performance.json` with QPS, p50/p95/p99 search latency, search mode distribution, and SLO gauges (Search Latency and Assessed Feed Latency).
- Codify `pipeline-system-health.json` with node durations, failure counts, and checkpoint latencies.
- Define Prometheus alert rules in `monitoring/prometheus/alert_rules.yml` for Search Latency SLO (SLO 1), Assessed Feed Latency SLO (SLO 2), and Pipeline Error Budget (SLO 3).

### Phase 6 — Verification & CI Metrics Integration Suite

**Depends on:** Q5 (resolved)  
**Reviewable when:** Automated integration test passes in CI asserting `/metrics` output, and live pipeline runs populate Grafana panels.  
**Touches:** `tests/integration/test_telemetry.py`

- Implement `tests/integration/test_telemetry.py` validating that API and worker metrics endpoints expose required metrics with valid types and labels.
- Verify live Grafana panel rendering and alert evaluations using real pipeline executions and API searches.

---

## Implementation notes

Recorded on 2026-09-08 after building all six phases. Where the shipped code differs from the design above, the code is authoritative.

- **`record_agent_usage` is a coroutine.** Cost lookup goes through the MongoDB-backed pricing cache (Q3), so the helper is `async` and every agent awaits it immediately after `await self.agent.run(...)`. Its failure path is swallowed and logged: telemetry cannot break an agent run.
- **Pricing is bound at process startup, not passed to agents.** `monitoring/pricing.py` exposes a process-wide `PricingCache`; the FastAPI lifespan and the pipeline runner each call `configure_pricing(mongo_client)`. Unbound caches (unit tests, offline runs) serve the static defaults, which keeps agents free of a MongoDB dependency.
- **Node labels use the graph's real node names.** `dedupe`, `persist_jobs`, and `cover_letter` rather than the `deduplicate`/`persist`/`generate_cover_letter` placeholders used while drafting.
- **Node instrumentation is a wrapper, not per-node code.** `instrument_nodes()` wraps each async node returned by `make_batch_nodes` and `make_pair_nodes`. Pair nodes absorb their exceptions into a skip reason instead of raising, so `_fail_pair` calls `mark_node_failed()` to flag the outcome for the wrapper.
- **Two metrics beyond the plan.** `dependency_up{dependency}` is published by `/readyz` to back the connectivity panel on Dashboard 3, and `http_requests_total` / `http_request_duration_seconds` come from the ASGI middleware in Phase 1, labelled by route template so path parameters cannot inflate cardinality.
- **Checkpoint latency via a subclass.** `orchestration/checkpointer.py` overrides `MongoDBSaver.put`; `aput` delegates to it in an executor thread, so one override covers both write paths.
- **Compose gained a `worker` service and explicit commands.** The Alloy scrape target `job-aggregator-worker:8001` needs a container to exist. The image ships no `CMD`, so both `api` and `worker` now declare one (`fastapi run` and `run-pipeline`).
- **Alloy `basic_auth` ships commented out.** An empty username/password block fails validation against the local Prometheus receiver; uncomment it when pointing `METRICS_REMOTE_WRITE_URL` at Grafana Cloud.
