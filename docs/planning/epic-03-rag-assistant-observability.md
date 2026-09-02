# Epic 3: Grounded RAG Assistant & Observability Dashboards

**Status:** Planned  
**Prerequisites:** Epic 2 (Hybrid search tier & embedding pipeline)  
**Scope:** Conversational RAG assistant with verifiable citations, streaming API, LLM token and cost telemetry, Prometheus/Grafana monitoring dashboards, and interactive chat UI.  
**Demonstrable Outcome:** A live career assistant answering complex domain queries with inline job citations, backed by Grafana dashboards showing exact token costs per pipeline cycle, search latencies, and system health metrics in real time.

---

## 1. Problem Statement & Motivation

1. **Unanswered High-Level Market Questions:** Candidates cannot easily synthesize market trends or query their fit across hundreds of postings (e.g. *"What tech stacks are most requested for Berlin senior Python roles, and where are my skill gaps?"*).
2. **Hallucination & Provenance Risk:** Standard LLM chat generates plausible-sounding advice without ground-truth citations to real job postings.
3. **LLM Cost & Operational Blind Spots:** Token consumption, agent execution latency, and error rates across multi-agent pipelines are invisible without fine-grained telemetry, making it impossible to budget or optimize costs accurately.

---

## 2. Vertical Slice Deliverables

### A. Grounded RAG Assistant Service
- **RAG Query Endpoint (`POST /rag/query`):**
  - Extract intent and filters from user natural language query.
  - Hybrid-retrieve top relevant job postings from OpenSearch scoped to candidate profile context.
  - Synthesize grounded response using PydanticAI / LLM agent with strict citation instructions (`[job:<uid>]`).
- **Safety & Token Control:**
  - Token budget guardrails to cap prompt and completion sizes.
  - Out-of-corpus refusal: explicitly refuse to answer when retrieval yields no relevant jobs rather than hallucinating.
- **Streaming Response:**
  - Support Server-Sent Events (SSE) or streaming chunks for low Time-to-First-Token (TTFT).

### B. RAG QA & Evaluation Suite
- **Groundedness & Citation Benchmark:**
  - Synthetic test suite of domain queries with known ground truth postings.
  - Automated evaluation of:
    - **Context Precision & Recall:** Were the necessary postings retrieved?
    - **Faithfulness:** Are all factual claims supported by the retrieved context?
    - **Citation Accuracy:** Do cited job UIDs contain the referenced requirements?
- **Load Testing (k6 / Locust):**
  - Performance benchmark script simulating concurrent search and RAG streaming queries under load (p50/p95/p99 latency tracking).

### C. Observability, Cost Accounting & Dashboards
- **Granular LLM Telemetry:**
  - Prometheus metrics exporter tracking:
    - `llm_tokens_total{agent="...", type="prompt|completion"}`
    - `llm_cost_estimated_usd_total{agent="...", model="..."}`
    - `pipeline_cycle_duration_seconds{node="..."}`
    - `search_query_duration_seconds{type="hybrid|bm25|vector"}`
- **Grafana Dashboards as Code (3 Core Views):**
  1. **LLM Cost & Token Accounting:** Per-cycle spend, spend-per-user, cost breakdown by agent (screening vs. fit assessment vs. cover letter vs. RAG), and budget burn rates.
  2. **Product & Search Performance:** Query throughput (QPS), p50/p95/p99 search latency, top filter combinations, and RRF fusion distribution.
  3. **Pipeline & System Health:** LangGraph node execution durations, failure rates, Mongo checkpoint write latencies, and memory/CPU usage.
- **Service Level Objectives (SLOs) & Alerts:**
  - Define and instrument 3 core SLOs:
    - **SLO 1 (Search Latency):** 95% of search queries respond in $< 150\text{ms}$.
    - **SLO 2 (RAG TTFT):** 90% of RAG queries yield first token in $< 1.5\text{s}$.
    - **SLO 3 (Pipeline Error Budget):** $< 0.5\%$ task failure rate per cycle.

### D. Frontend RAG Assistant UI
- **Interactive Chat Interface:**
  - Slide-out assistant drawer or dedicated chat page in React UI.
  - Streaming token rendering for smooth real-time reading experience.
  - Interactive citation badges: clicking a `[job:123]` citation opens the referenced job card and highlights the matching criteria.

---

## 3. Step-by-Step Execution Plan

| Step | Task | Deliverable |
| --- | --- | --- |
| **3.1** | RAG retrieval & prompt engine | `agents/rag_assistant.py`, citation parser, refusal rules. |
| **3.2** | Streaming RAG endpoint | `POST /rag/query` with SSE / streaming chunk support. |
| **3.3** | RAG evaluation benchmark | `benchmarks/rag/` measuring faithfulness and citation precision. |
| **3.4** | LLM cost & Prometheus instrumentation | Prometheus metrics exporter, agent token counter hooks. |
| **3.5** | Grafana dashboards as code | Provisioned Grafana dashboard JSONs (Cost, Search, System Health). |
| **3.6** | Load test script (k6) | `tests/load/k6-search-rag.js` with documented p95 baselines. |
| **3.7** | React UI chat component | Streaming chat box with interactive citation badge preview cards. |

---

## 4. Acceptance Criteria & Verification

- [ ] Sending a query to `POST /rag/query` returns a streamed markdown response containing valid `[job:<uid>]` inline citations.
- [ ] Asking an out-of-corpus query (e.g. *"What is the weather in Tokyo?"*) triggers an appropriate polite refusal without making invalid claims.
- [ ] Running a pipeline cycle or RAG query immediately updates Prometheus counters and reflects exact token counts and estimated USD costs in Grafana.
- [ ] Three Grafana dashboards load without errors, displaying live data when traffic is simulated with the k6 script.
- [ ] React UI renders streamed assistant answers and lets users click citation badges to view the source job posting.
