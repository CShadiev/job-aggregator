# Master Roadmap: Flagship Demo Epics

**Status:** Approved Modular Roadmap  
**Architecture Theme:** High-performance, observable AI job aggregator with hybrid retrieval, RAG, automated quality gates, and progressive canary deployments.

---

## 1. Executive Summary & Why the Epic was Restructured

The original flagship demo plan attempted to build the entire cloud infrastructure, Kubernetes cluster, and CI/CD pipelines before validating application retrieval and RAG logic locally. This created an inverted feedback loop with significant upfront operational risk.

This revised roadmap splits the project into **4 distinct vertical-slice epics**. Each epic delivers demonstrable value across the entire stack (**Application + QA/Benchmarks + CI + Telemetry + UI**), ensuring every phase results in a working, verifiable product milestone:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Epic 1: Developer Foundation, CI Quality Gates & Baseline Telemetry                   │
│ ➔ Working local compose stack + full CI testing + OTel tracing + UI context connected  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Epic 2: Hybrid Search & Retrieval Evaluation Harness (The Cost Killer)                 │
│ ➔ OpenSearch + O(users × K) pipeline + Gold Set Benchmarks (Recall/nDCG) + Search UI   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Epic 3: Grounded RAG Assistant & Observability Dashboards                             │
│ ➔ Streaming RAG with citations + Prometheus Cost Metrics + 3 Grafana Dashboards + UI   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Epic 4: Production Packaging, Canary Deployments & Infrastructure as Code             │
│ ➔ Terraform IaC + Argo Rollouts Canary Auto-Rollback + Production CD + Senior ADRs    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Epic Breakdown & Links

### [Epic 1: Developer Foundation, CI Quality Gates & Baseline Telemetry](./epic-01-dev-env-ci-telemetry.md)
* **Goal:** Establish a fast, reliable local feedback loop with automated PR quality gates and baseline request tracing.
* **Key Deliverables:**
  - `docker-compose.yml` orchestrating MongoDB, OpenSearch (single node), and local API/Worker.
  - Complete codebase hygiene (cleanup of legacy `workers/job_processing.py` and old collections).
  - Multi-stage optimized `Dockerfile` (pinned digest, non-root user).
  - GitHub Actions PR gate (`ruff` lint/format, `mypy` type check, `pytest` unit + integration tests).
  - Structured JSON logging with `cycle_id` and `request_id` correlation via OpenTelemetry.
  - Clone/link frontend into ignored `react-app/` directory and verify API connectivity.
* **Demonstrable Outcome:** A clean PR workflow where every push is verified in CI against a multi-service containerized environment with end-to-end tracing.

---

### [Epic 2: Hybrid Search & Retrieval Evaluation Harness](./epic-02-hybrid-search-retrieval-eval.md)
* **Goal:** Solve the $O(\text{users} \times \text{jobs})$ pipeline cost problem with hybrid search and prove ranking quality with hard benchmark numbers.
* **Key Deliverables:**
  - OpenSearch index schema with BM25 (analyzers, synonyms) + k-NN dense vector embeddings (`text-embedding-3-small`).
  - Search pipeline with Reciprocal Rank Fusion (RRF) / score normalization.
  - LangGraph `embed_jobs` ingestion node and historical embedding backfill script.
  - Retrieval-gated `build_pairs` node reducing candidate pairings from Cartesian product to top-$K$.
  - Upgraded `POST /jobs/search` API with keyword search and faceted filtering.
  - Offline retrieval benchmark suite (`benchmarks/retrieval/`) calculating **Recall@K, nDCG@K, and MRR** across BM25, Vector, and Hybrid RRF on a curated gold set.
  - Connect React UI search bar and faceted filter chips.
* **Demonstrable Outcome:** 80–90% reduction in pipeline LLM calls with benchmark proof of superior hybrid retrieval accuracy and full-text faceted search in the UI.

---

### [Epic 3: Grounded RAG Assistant & Observability Dashboards](./epic-03-rag-assistant-observability.md)
* **Goal:** Provide conversational intelligence with inline citations while bringing full visibility to LLM costs and system performance.
* **Key Deliverables:**
  - Streaming RAG assistant endpoint (`POST /rag/query`) synthesizing candidate profiles and retrieved postings with verifiable `[job:<uid>]` inline citations.
  - Token budgeting and strict refusal on out-of-corpus queries.
  - RAG evaluation harness checking context precision, faithfulness, and citation accuracy.
  - Prometheus metrics exporter for per-agent token counts and estimated USD costs.
  - 3 Grafana dashboards as code: (1) LLM Token & Cost Accounting, (2) Product & Search Performance, (3) Pipeline & System Health.
  - 3 Documented SLOs with alerting thresholds.
  - k6 load test script benchmarking concurrent search and RAG streaming queries.
  - Interactive React UI assistant chat drawer with clickable citation badges.
* **Demonstrable Outcome:** An interactive career assistant with verifiable citations, supported by real-time Grafana dashboards tracking exact dollar spend and latency.

---

### [Epic 4: Production Packaging, Canary Deployments & Infrastructure as Code](./epic-04-production-packaging-canary-iac.md)
* **Goal:** Package the verified application for reproducible cloud deployment with safe progressive delivery and documented architectural decisions.
* **Key Deliverables:**
  - Modular Terraform configurations (compute, networking, TLS, storage) with remote state and one-command teardown (`make infra-up`, `make infra-down`).
  - GitHub Actions CD pipeline deploying to cloud runtime on merge to `main`.
  - Argo Rollouts canary deployment gated on Prometheus latency SLOs and retrieval smoke tests.
  - Automated canary rollback simulation with a recorded video/log proof artifact.
  - Horizontal Pod Autoscaling (HPA) for API and scheduled/scale-to-zero scaling for pipeline workers.
  - 6–8 Architecture Decision Records (ADRs) in `docs/adr/`.
  - 5-minute live demo script and comprehensive runbook.
* **Demonstrable Outcome:** A public cloud deployment with zero-downtime canary releases, automated failure rollback, and portfolio-grade ADR documentation.

---

## 3. Recommended Sequencing

```
Week 1: Epic 1 (Foundation, CI & Telemetry) ➔ Developer velocity unlocked
Week 2: Epic 2 (Hybrid Search & Retrieval Eval) ➔ Core cost & search problem solved
Week 3: Epic 3 (RAG Assistant & Dashboards) ➔ Interactive AI & monitoring complete
Week 4: Epic 4 (Canary CD, Terraform & ADRs) ➔ Production cloud packaging
```
