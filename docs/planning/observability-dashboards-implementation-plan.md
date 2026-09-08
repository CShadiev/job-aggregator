# Observability, Cost Accounting & Dashboards — Implementation Plan

**Status:** Draft  
**Last updated:** 2026-09-08  
**Open questions:** 5  
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
  - Capturing PydanticAI `RunUsage` (`input_tokens`, `output_tokens`, `total_tokens`) across all agents (`ScreeningAgent`, `FitAssessmentAgent`, `CoverLetterGenerationAgent`, `DeduplicationAgent`).
  - Real-time estimated USD cost computation based on configurable model pricing tables.
  - Metrics labeled by agent name, model identifier, and token direction (`prompt` vs. `completion`).
- **Search & Pipeline Health Instrumentation:**
  - Instrumentation of OpenSearch operations in `SearchService` (query duration by search mode `hybrid|bm25|knn|feed`, result counts).
  - Instrumentation of LangGraph cycle and node durations (`collect`, `normalize`, `deduplicate`, `persist`, `build_pairs`, `embed_jobs`, `finalize`, `screen`, `assess`, `generate_cover_letter`).
  - Tracking of task execution success vs. failure rates and MongoDB checkpoint latency.
- **Local Observability Stack in `docker-compose.yml`:**
  - Containerized Prometheus instance with automated scraping of API and worker endpoints.
  - Containerized Grafana instance with automated provisioning (datasources and dashboards as code).
- **Grafana Dashboards as Code (3 Core Views):**
  1. **LLM Cost & Token Accounting Dashboard:** Visualizing cumulative and per-cycle token consumption, USD spend breakdown by agent, cost per candidate/cycle, and burn rate.
  2. **Product & Search Performance Dashboard:** Visualizing query throughput (QPS), p50/p95/p99 search latency, distribution by search mode (`hybrid`, `bm25`, `knn`, `feed`), and RRF score distributions.
  3. **Pipeline & System Health Dashboard:** Visualizing LangGraph node execution durations, error budget depletion, failure counts by node/task, and MongoDB/OpenSearch connectivity status.
- **SLO Definitions & Alert Rules:**
  - Codified Prometheus alerting rules for Search Latency SLO (95% < 150ms) and Pipeline Error Budget (< 0.5% task failure rate).
- **Synthetic Traffic & Verification Harness:**
  - Script to generate synthetic search traffic and execute test pipeline cycles, verifying end-to-end metrics flow and dashboard panel rendering.

### Out of scope

- Conversational RAG assistant service (`POST /rag/query`), citation parser, streaming tokens, and chat frontend (deferred from Epic 3A/3D).
- RAG ground-truth evaluation benchmark suite (deferred from Epic 3B).
- Cloud Kubernetes deployment, Terraform IaC, and Argo Rollouts progressive canary delivery (deferred from Epic 4).
- Production multi-tenant billing or payment gateway integrations (internal cost estimation only).

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
| **Search Service** | `search/search_service.py:154-222` | Houses `search_jobs` (`bm25`, `knn`, `hybrid`) and `search_user_feed`. Already creates OTel spans; needs Prometheus latency histograms by search mode. |
| **Local Services** | `docker-compose.yml:1-92` | Defines local containers (`mongodb`, `opensearch`, `opensearch-dashboards`, `api`). Must be extended with `prometheus` and `grafana` services. |
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
                                   │ scrapes :8000/metrics
┌──────────────────────────────────┴─────────────────────────────────────┐
│ Prometheus Server (:9090)                                              │
│  ├── Scrapes FastAPI (:8000) & Pipeline Worker (:8001 or Pushgateway)   │
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
                                   │ scrapes :8001/metrics
┌──────────────────────────────────┴─────────────────────────────────────┐
│ LangGraph Pipeline Runner (:8001)                                      │
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
  - Labels: `node` (`collect`, `normalize`, `deduplicate`, `persist`, `build_pairs`, `embed_jobs`, `finalize`, `screen`, `assess`, `generate_cover_letter`).
  - Buckets: `[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]`.
- **`pipeline_tasks_total`** (Counter):
  - Description: Total pair and batch tasks processed.
  - Labels: `node`, `status` (`success`, `failure`).
- **`mongo_checkpoint_duration_seconds`** (Histogram):
  - Description: Duration of Mongo checkpoint write operations by `MongoDBSaver`.
  - Buckets: `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]`.

### Dashboards as Code & Provisioning

All Grafana dashboards and datasources are codified in the repository under `monitoring/`:

```
monitoring/
├── prometheus/
│   ├── prometheus.yml          # Scrape configs for api (:8000) and worker (:8001)
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
- **Top Row KPI Gauges:** Current Search QPS, p95 Search Latency, p99 Search Latency, Search Error Rate.
- **Latency Distribution (Heatmap/Timeseries):** `search_query_duration_seconds` p50, p95, and p99 percentiles over time by mode (`hybrid`, `bm25`, `knn`, `feed`).
- **Throughput by Query Type (Timeseries):** Breakdown of traffic across hybrid, keyword-only, vector-only, and assessed feed queries.
- **SLO Gauge:** Percentage of search queries meeting the $< 150\text{ms}$ threshold over a rolling 1-hour window.

#### Dashboard 3: Pipeline & System Health
- **Top Row KPI Gauges:** Pipeline Active Status, Last Cycle Duration, Task Success Rate (%), Failed Tasks Count.
- **Node Execution Times (Bar / Timeseries):** p95 latency for each LangGraph node (`embed_jobs`, `build_pairs`, `screen`, `assess`, etc.).
- **Task Failure Trend (Timeseries):** Failed tasks per node over time.
- **Checkpoint & Database Latency:** Mongo checkpoint write duration p95 and OpenSearch bulk indexing duration.

### SLO Definitions & Alert Rules

Prometheus alert rules evaluate against Prometheus recording metrics:
1. **SLO 1 — Search Latency:**
   - Objective: $\ge 95\%$ of search queries respond in $< 150\text{ms}$ over a 5-minute evaluation window.
   - PromQL:
     ```promql
     sum(rate(search_query_duration_seconds_bucket{le="0.15"}[5m]))
     /
     sum(rate(search_query_duration_seconds_count[5m])) < 0.95
     ```
   - Alert: `SearchLatencySLOBreach` (Severity: warning).
2. **SLO 2 — Pipeline Error Budget:**
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

### Q1 — Metrics Exposition Architecture across Multi-Process Boundaries

**Blocks:** Phase 1 (Prometheus Metrics Engine), Phase 4 (`docker-compose.yml` scrape configuration).  
**Context:** FastAPI runs as an HTTP server (`main.py`, port 8000), while the LangGraph pipeline is a standalone CLI scheduler (`orchestration/runner.py`). They run in separate OS processes and separate containers in `docker-compose`.  
Prometheus must scrape metrics from both execution contexts.  
**Options:**
- *Option A (Dual scrape targets):* FastAPI exposes `/metrics` on port 8000. `orchestration/runner.py` starts a lightweight background HTTP server via `prometheus_client.start_http_server(port=8001)` inside its container. Prometheus scrapes both `job-aggregator-api:8000` and `job-aggregator-worker:8001`.
- *Option B (Prometheus Pushgateway):* Deploy a `pushgateway` container in `docker-compose`. At the completion of each pipeline cycle in `orchestration/runner.py`, metrics are pushed to the gateway, while FastAPI exposes `/metrics` directly.
- *Option C (Prometheus multiprocess mode):* Configure `prometheus_client` multiprocess mode pointing to a shared volume (`PROMETHEUS_MULTIPROC_DIR`), with FastAPI exposing aggregated metrics.  
**Leaning:** Option A. It requires no additional Pushgateway container, avoids the concurrency and cleanup pitfalls of multiprocess directory locking on file systems, and treats the worker as a standard Prometheus scrape target.

---

### Q2 — Agent Token & Cost Instrumentation Pattern

**Blocks:** Phase 2 (Agent Token & Cost Accounting).  
**Context:** Four agents call PydanticAI models via `await self.agent.run(...)`:
- `ScreeningAgent.screen` (`agents/screening.py:38`)
- `FitAssessmentAgent.assess` (`agents/fit_assessment.py:58`)
- `CoverLetterGenerationAgent.generate` (`agents/cover_letter_generation.py:52`)
- `DeduplicationAgent._process_batch` (`agents/deduplication.py:73`)  
PydanticAI returns a `RunResult` containing `result.usage()`, which provides `input_tokens` and `output_tokens`.  
**Options:**
- *Option A (Direct agent hook / helper):* Create an instrumentation module `telemetry_metrics.py` with a helper `record_agent_usage(agent_name: str, model_name: str, usage: RunUsage, duration_seconds: float)`. Call this helper directly after `self.agent.run(...)` in each agent class.
- *Option B (Custom agent wrapper / decorator):* Subclass or wrap `pydantic_ai.Agent` to automatically intercept `.run()` and record tokens/cost transparently to all agents.
- *Option C (OpenTelemetry to Prometheus bridge):* Rely exclusively on OpenTelemetry GenAI spans and export them into Prometheus via the OpenTelemetry collector.  
**Leaning:** Option A. It is explicit, has zero framework monkey-patching risk, avoids introducing the heavyweight OpenTelemetry Collector binary, and directly updates the Prometheus `Counter` and `Histogram` with exact pricing logic.

---

### Q3 — Rate Card & Cost Calculation Storage

**Blocks:** Phase 2 (Cost calculation logic).  
**Context:** Models in `agents/model_factory.py` (`gpt-5.6-luna`, `gpt-5-mini`, `grok-4.3`, etc.) have distinct input and output token pricing (e.g. $X / 1M prompt tokens, $Y / 1M completion tokens). Embeddings (`text-embedding-3-small`) also carry token costs.  
**Options:**
- *Option A (Code-level rate card with defaults):* Maintain a rate card dictionary in a dedicated module (e.g. `monitoring/pricing.py` or `telemetry_metrics.py`) mapping model names to `(input_usd_per_1m, output_usd_per_1m)`, with an environment variable override for custom rates.
- *Option B (Configuration settings in `config.py`):* Define structured pricing settings in Pydantic `Config` (e.g. `MODEL_PRICING: dict[str, tuple[float, float]]`).
- *Option C (Dynamic MongoDB collection):* Store model prices in a `pricing` collection in MongoDB, editable via admin endpoints.  
**Leaning:** Option A with fallback in `ConfigProvider`. Token prices change infrequently; managing them in code with clean fallbacks avoids database coupling for a telemetry exporter.

---

### Q4 — Adaptation of Deferred RAG SLO

**Blocks:** Phase 5 (SLO & Alerting definitions).  
**Context:** Epic 3 (Section C) originally defined 3 SLOs:
1. Search Latency: 95% < 150ms.
2. RAG TTFT: 90% < 1.5s.
3. Pipeline Error Budget: < 0.5% task failure rate per cycle.  
Since RAG is deferred, SLO 2 needs an appropriate operational target for the active search and pipeline systems.  
**Options:**
- *Option A (API Availability & Feed Latency):* Replace SLO 2 with Assessed Feed Latency: 95% of `POST /jobs/search` feed queries respond in $< 200\text{ms}$.
- *Option B (Embedding Pipeline Latency):* Replace SLO 2 with Batch Embedding Throughput: 95% of job embedding batches complete in $< 1.0\text{s}$.
- *Option C (Omit SLO 2):* Retain only 2 core SLOs (Search Latency and Pipeline Error Budget) until RAG is implemented.  
**Leaning:** Option A. It provides a client-facing latency SLO on the primary feed endpoint without waiting for RAG.

---

### Q5 — Synthetic Workload & Verification Strategy

**Blocks:** Phase 6 (Verification & Synthetic Traffic).  
**Context:** After provisioning Grafana dashboards, panels require live metrics to display meaningful graphs and verify alert trigger logic.  
**Options:**
- *Option A (Standalone Python generator script):* Provide a script `scripts/simulate_telemetry_traffic.py` that hits `/jobs/search` with diverse query types (`hybrid`, `bm25`, `knn`, empty) and triggers a mock or real pipeline cycle via `run_once(graph)`.
- *Option B (k6 load testing script):* Implement `tests/load/k6-search-telemetry.js` executed via a k6 Docker service in `docker-compose`.
- *Option C (Pytest integration test harness):* Write an automated test in `tests/integration/test_telemetry_dashboards.py` that queries `/metrics` after simulated traffic and asserts expected counters and histogram buckets are populated.  
**Leaning:** Combination of Option A (for manual/live visual dashboard verification) and Option C (for automated CI validation).

---

## Decision log

Empty at kickoff. As open questions are deliberated with the user, resolved decisions will be recorded here with their rationale and rejected alternatives.

---

## Suggested question sequence

1. **Q1 (Metrics Exposition Architecture)** — Fundamental architectural decision determining how the pipeline worker and API expose metrics to Prometheus and how `docker-compose.yml` is wired.
2. **Q2 (Agent Token & Cost Instrumentation Pattern)** — Directly dictates how `ScreeningAgent`, `FitAssessmentAgent`, `CoverLetterGenerationAgent`, and `DeduplicationAgent` are modified to feed usage data.
3. **Q3 (Rate Card & Cost Calculation Storage)** — Determines pricing configuration structure and model cost formula.
4. **Q4 (Adaptation of Deferred RAG SLO)** — Finalizes the 3rd SLO target to codify in Prometheus alert rules.
5. **Q5 (Synthetic Workload & Verification Strategy)** — Shapes the verification scripts and tests for certifying the dashboards.

---

## Implementation phases

### Phase 1 — Prometheus Metrics Engine & API Instrumentation

**Depends on:** Q1  
**Reviewable when:** `GET /metrics` on FastAPI returns standard Prometheus metrics format with process and HTTP metrics.  
**Touches:** `pyproject.toml`, `telemetry.py`, `main.py`, `api/middleware/`

- Add `prometheus-client` to `pyproject.toml`.
- Create `monitoring/metrics.py` defining Prometheus metrics singletons (`llm_tokens_total`, `llm_cost_estimated_usd_total`, `search_query_duration_seconds`, `pipeline_cycle_duration_seconds`, etc.).
- Mount `/metrics` endpoint on the FastAPI application in `main.py`.
- Add ASGI middleware to track HTTP request count and latency percentiles.

### Phase 2 — Agent LLM Token & Cost Accounting

**Depends on:** Q2, Q3  
**Reviewable when:** Running any agent (`screening`, `fit_assessment`, `cover_letter`, `deduplication`) immediately increments `llm_tokens_total` and `llm_cost_estimated_usd_total` with correct labels.  
**Touches:** `agents/screening.py`, `agents/fit_assessment.py`, `agents/cover_letter_generation.py`, `agents/deduplication.py`, `monitoring/pricing.py`

- Implement `monitoring/pricing.py` with the model rate card and USD calculation helper.
- Update each agent's execution method to capture `result.usage()` and report input/output tokens and cost to `monitoring/metrics.py`.
- Unit tests validating that token counts and cost calculations match expected formulas.

### Phase 3 — Search & LangGraph Pipeline Instrumentation

**Depends on:** Q1  
**Reviewable when:** Executing `SearchService` queries and running pipeline cycles populates search duration histograms and pipeline node timing metrics.  
**Touches:** `search/search_service.py`, `orchestration/nodes/batch.py`, `orchestration/nodes/pair.py`, `orchestration/runner.py`

- Instrument `search_jobs` and `search_user_feed` in `SearchService` to record `search_query_duration_seconds` and `search_feed_query_duration_seconds`.
- Instrument batch and pair nodes in `orchestration/nodes/` to record execution duration and task outcome (`success` vs. `failure`).
- Instrument pipeline runner (`orchestration/runner.py`) to expose metrics (via dedicated port or selected Q1 mechanism) and record cycle duration.

### Phase 4 — Local Observability Infrastructure

**Depends on:** Q1  
**Reviewable when:** `docker compose up -d` boots `prometheus` and `grafana`, Prometheus targets are in `UP` state, and Grafana is accessible on `:3000`.  
**Touches:** `docker-compose.yml`, `monitoring/prometheus/prometheus.yml`, `monitoring/grafana/provisioning/`

- Add `prometheus` service to `docker-compose.yml` with scrape configuration for `api` and `worker`.
- Add `grafana` service to `docker-compose.yml` with pre-configured Prometheus datasource provisioning.
- Enable anonymous authentication for local Grafana development.

### Phase 5 — Grafana Dashboards as Code & Alert Rules

**Depends on:** Q4  
**Reviewable when:** Opening Grafana shows 3 fully configured dashboards (`LLM Cost & Token Accounting`, `Product & Search Performance`, `Pipeline & System Health`) with active alert rules.  
**Touches:** `monitoring/grafana/dashboards/*.json`, `monitoring/prometheus/alert_rules.yml`

- Codify `llm-cost-accounting.json` with token burn rates, agent cost breakdown, and per-user/cycle spending.
- Codify `search-performance.json` with QPS, p50/p95/p99 search latency, search mode distribution, and SLO gauge.
- Codify `pipeline-system-health.json` with node durations, failure counts, and checkpoint latencies.
- Define Prometheus alert rules in `monitoring/prometheus/alert_rules.yml` for Search Latency SLO and Pipeline Error Budget.

### Phase 6 — Synthetic Traffic Generator & Verification Suite

**Depends on:** Q5  
**Reviewable when:** Running the synthetic traffic generator populates all Grafana panels with realistic timeseries data and tests pass in CI.  
**Touches:** `scripts/simulate_telemetry_traffic.py`, `tests/integration/test_telemetry.py`

- Create `scripts/simulate_telemetry_traffic.py` to drive hybrid search, keyword search, assessed feed queries, and a mock pipeline run.
- Write automated integration test verifying that `/metrics` contains expected metrics and labels after execution.
