# Epic: Flagship Demo — High-Level Outline

**Status:** draft outline; platform, search tier, demo surface and cost ceiling settled (§6)
**Budget:** 3 weeks × 40 h = **120 h**
**Stack:** managed Kubernetes + Terraform, OpenSearch, Argo Rollouts canary, thin React UI, ~$65/mo
**Goal:** turn this service into the single project a hiring manager can open, run, read, and interrogate — and that produces fluent answers to senior-level interview questions.

***

## 1. The problem this epic actually solves

Everything below has to hang off a real product problem, otherwise the infrastructure
reads as CV decoration. Fortunately the project already has one, and it is a good one.

Today the pipeline fans out over the **Cartesian product** of users × unique jobs
(`build_pairs` in `orchestration/nodes/batch.py`) and spends an LLM call on every pair.
Screening was added as a cheap gate, but the cost curve is still **O(users × jobs)**:

* 500 new jobs/day × 50 users = 25 000 screening calls/day before any real assessment.
* The feed itself has no search — `POST /jobs/search` is a Mongo aggregation over
  `assessments` with a `$lookup` into `jobs`, skip-based pagination, and sorting after
  the join. It cannot answer "Kubernetes jobs in Berlin" at all, only filter on
  pre-computed scores.

So the spine of the epic is one sentence:

> **Replace the brute-force fan-out with hybrid retrieval, so LLM cost becomes
> O(users × K) instead of O(users × jobs) — then build the infrastructure needed to
> prove the savings, protect ranking quality, and scale the read path.**

Every requested capability falls out of that one problem, in order:

| Requested capability          | Why the product needs it (not contrived)                                                                                                                                              |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hybrid search (vector + BM25) | Reduces LLM spend by 1–2 orders of magnitude and makes the feed searchable. This *is* the feature.                                                                                    |
| OpenSearch                    | The BM25 leg, the kNN leg, and RRF fusion in one system; also gives the API real full-text search, which it has never had.                                                            |
| RAG                           | Once the corpus is retrievable, "what does the Berlin market want from a senior Python engineer?" is answerable with citations. New user-facing value from existing data.             |
| Observability                 | LLM cost/cycle and retrieval quality are the two things you cannot debug or prove without telemetry. The savings claim needs evidence.                                                |
| Canary / blue-green           | The risk surface is *ranking quality*, which degrades silently. A deploy gate on retrieval metrics + latency SLO is a genuine need, not a checkbox.                                   |
| Autoscaling behind an LB      | Search and RAG endpoints are bursty and hold long-lived LLM calls; the batch pipeline should scale to zero between cycles.                                                            |
| Terraform                     | The stack goes from one container to API + worker + Mongo + a stateful search cluster + object storage + LB + TLS. Reproducibility and *teardown* are real needs at a $75/mo ceiling. |
| Performance work              | The feed aggregation, the embedding path, and cold-start latency are all measurable.                                                                                                  |
| ADRs                          | Each of the above involved a rejected alternative worth defending out loud.                                                                                                           |

***

## 2. Baseline: what exists vs. what is missing

**Exists**

* LangGraph pipeline with Mongo checkpointing, idempotent nodes, failure collection.
* 4 PydanticAI agents (normalize, screen, assess, cover letter) with offline benchmark harnesses under `benchmarks/`.
* FastAPI + Auth0, S3-compatible storage, Docker image, unit + integration tests.
* Design already written: `docs/candidate-job-ranking.md` (hybrid search), `docs/planning/langgraph-pipeline.md`.

**Missing (the epic's surface area)**

* No IaC, no deployment target, no load balancer, no scaling.
* CI only builds and pushes an image on `v*` tags — **no tests, no lint, no type check, no CD**.
* No metrics, no traces, no dashboards, no SLOs, no cost accounting.
* No search tier, no embeddings, no reranking.
* No frontend of any kind.
* Dead weight: legacy `workers/job_processing.py` + `job_processing` / `failed_entries` collections.

***

## 3. Budget reality and the AI multiplier

The multiplier is not uniform, and planning as if it were is the main way this epic fails.

| Work type                                                | AI multiplier   | Notes                                                                  |
| -------------------------------------------------------- | --------------- | ---------------------------------------------------------------------- |
| Application code, tests, retrieval logic, RAG            | **high (3–5×)** | Well-trodden patterns, fast local feedback loop.                       |
| Terraform, CI/CD wiring, dashboards                      | medium (1.5–2×) | AI writes the HCL fine; the time goes to `terraform apply` cycles.     |
| Cloud IAM, networking, DNS, TLS, first successful deploy | **low (~1×)**   | Wall-clock bound. Debugging a 5-minute apply loop is not compressible. |
| Writing (ADRs, README, demo script)                      | high (3×)       | But needs real judgement input, so budget thinking time.               |

**Implication:** front-load a thin infrastructure slice early rather than saving infra
for the end. Get *something* deployed in week 1 so the low-multiplier work is
de-risked while there is still schedule to absorb it, then ship every later feature
through the pipeline you built. This is also better engineering practice and a better
story than "and then at the end I added Terraform."

Split of the 120 h, reflecting the decisions in §6:

| Bucket                                          | Hours   | Share |
| ----------------------------------------------- | ------- | ----- |
| Infrastructure (Terraform, k8s, CI/CD, canary)  | 38      | 31 %  |
| Hybrid search + retrieval-gated pipeline + eval | 38      | 31 %  |
| Observability + performance                     | 15      | 12 %  |
| RAG assistant                                   | 12      | 10 %  |
| Demo UI                                         | 10      | 8 %   |
| ADRs, README, demo script                       | 8       | 7 %   |
| **Total**                                       | **121** |       |

That is 121 h against a 120 h budget with **zero buffer**, so §7's cut list is not
optional reading — it is the schedule's only slack.

Worth noting *why* the Kubernetes choice does not blow this up further. Standing up
managed k8s costs ~10 h more than a managed container service, but it hands back most
of that downstream, because three of the epic's requirements are built-in primitives
rather than bespoke work:

| Requirement                    | On k8s                                                                   | Saved |
| ------------------------------ | ------------------------------------------------------------------------ | ----- |
| Autoscaling behind an LB       | HPA + Service/Ingress, already there                                     | ~3 h  |
| Monitoring stack               | one `kube-prometheus-stack` Helm release                                 | ~3 h  |
| Canary with automatic rollback | Argo Rollouts `AnalysisTemplate` querying the Prometheus you already run | ~2 h  |

The last row is the important one: on k8s the observability investment *is* the deploy
gate, so those two line items stop being separate work. Net cost of the k8s decision is
about +2 h, not +10 h.

***

## 4. Scope

### In scope (the committed core)

1. **Search tier.** OpenSearch index over `jobs` with BM25 on title/description/tags
   plus a `knn_vector` field, fused with RRF via a search pipeline.
2. **Embedding at ingestion.** New pipeline node after `persist_jobs`; backfill script
   for existing jobs. Candidate-side embeddings on profile change.
3. **Retrieval-gated assessment.** `build_pairs` becomes "retrieve top-K jobs per user"
   instead of a Cartesian product. Screening stays as the second gate.
4. **Real search API.** `POST /jobs/search` gains free-text + faceted search backed by
   the search tier; the existing score/filter semantics are preserved.
5. **Retrieval evaluation harness.** Small gold set, Recall@K / nDCG / MRR, following
   the existing `benchmarks/` pattern. This is what separates "I built RAG" from
   "I built RAG and can tell you how good it is."
6. **RAG assistant.** Grounded Q\&A over the job corpus + the user's own CV, with
   inline citations back to job UIDs. Streaming response.
7. **Terraform** for the whole stack, remote state, one command up / one command down.
   One live environment, with modules parameterised so a second is a variable file
   rather than a rewrite; teardown-and-recreate demonstrated rather than a second
   cluster left running (the cost ceiling does not stretch to two). "One command" is a
   `Makefile` target wrapping two applies with the CRD bootstrap between them — the
   boundary is deliberate, see ADR 0001 — not a single `terraform apply`.
8. **Real CI/CD.** PR gate (lint, type check, unit + integration tests, image build) →
   deploy on merge → **canary** with automatic rollback on SLO breach.
9. **Autoscaling behind a load balancer** for the API; scale-to-zero or scheduled
   scaling for the pipeline worker.
10. **Observability.** OpenTelemetry traces end-to-end, Prometheus metrics, Grafana
    dashboards, and — the differentiating one — **LLM token/cost metrics per pipeline
    cycle and per agent**, plus retrieval-quality metrics. 3 documented SLOs, one of
    which doubles as the canary gate.
11. **Performance pass.** Feed aggregation and index tuning, response caching,
    keyset pagination, embedding batching, container cold-start. All with
    before/after numbers from a load test.
12. **8–10 ADRs**, one per real decision, in `docs/adr/`.

### Stretch (do only if ahead of schedule)

* Cross-encoder reranking stage on top of RRF.
* Description enrichment agent (structured role/seniority/requirements extraction) —
  would meaningfully improve retrieval, but it is a whole agent + benchmark.
* Query understanding (LLM parses "remote senior python berlin" into filters).
* Chaos/failure-injection demo.

### Explicitly out of scope

* Service mesh, multi-region, multi-tenancy at scale.
* Self-managed control plane, custom operators, GitOps (Argo CD) on top of Argo
  Rollouts. Rollouts alone covers the canary requirement. Argo CD *would* be the
  clean answer to CRD ordering (sync waves) and would come with drift self-healing,
  but it costs 6–10 h against a zero-buffer plan and its controller/repo-server/redis
  footprint is a genuine capacity risk on 2 × 4 GB nodes that also carry OpenSearch
  and `kube-prometheus-stack`. Rejected explicitly in
  [ADR 0001](../adr/0001-gateway-api-crd-installation.md), option E.
* Postgres/pgvector migration.
* Tailored CV generation, notification service, StepStone/Indeed collectors (roadmap
  items unrelated to this epic's spine).
* Any rewrite of agent prompts or assessment semantics.

### Cheap wins worth taking (~2 h total)

* Delete `workers/job_processing.py` and its collections. A reviewer reading two
  parallel orchestration paths will assume the codebase is unloved.
* Multi-stage Dockerfile, non-root user, pinned base digest, `.dockerignore`.
  Currently the image is a single stage that `COPY . .` including `.venv` and `logs`.
* Fix `CORSMiddleware` `allow_origins=["*"]` + `allow_credentials=True` — that
  combination is a red flag any reviewer will spot in 10 seconds.

***

## 5. Week-by-week outline

### Week 1 — Ship a deployment, then build the search core (40 h)

Goal by Friday: **a public URL, deployed by CI, serving hybrid search.**

| #   | Work                                                                                                                                                              | h   |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 1.1 | Confirm stack (§6), Atlas M0 size check, secrets hygiene. Cheap wins from §4.                                                                                     | 4   |
| 1.2 | Terraform in two stacks: `dev` (VPC, DOKS cluster, node pool, Spaces bucket, registry) and `cluster-services` (Traefik + cert-manager, `GatewayClass`/`Gateway`/`ClusterIssuer`, DNS + TLS). Remote state, one environment. CRDs are *not* Terraform's job — see 1.2b and ADR 0001. | 11  |
| 1.2b | `scripts/bootstrap-cluster.sh`: idempotent `kubectl apply --server-side` of the Gateway API CRDs, with explicit cluster verification. Runs between the two Terraform stacks; wrapped with them in a `Makefile` up/down target so "one command up" still holds. | 1   |
| 1.3 | Helm chart / manifests for API + pipeline worker + OpenSearch StatefulSet (PVC, heap, k-NN plugin).                                                               | 6   |
| 1.4 | CI gate: lint (`ruff`), type check, unit tests, integration tests against service containers, image build + push to registry. CD to the cluster on merge to main (bootstrap script → `cluster-services` apply → `helm upgrade`); needs `kubectl` + `doctl` in the runner. | 6   |
| 1.5 | Minimal telemetry: OTel auto-instrumentation for FastAPI + pymongo, structured logs queryable. Enough to debug the rest of the epic.                              | 3   |
| 1.6 | Search index: mapping, analyzers, tag synonym dictionary (`k8s`→`kubernetes`), dual-write from `persist_jobs`, backfill script.                                   | 6   |
| 1.7 | Hybrid query: `hybrid` query + search pipeline with `score-ranker-processor` (RRF) behind a `SearchService`. Wire into `POST /jobs/search`.                       | 5   |

Risk markers, because this is the week that can eat the epic:

* If the cluster is not serving traffic by **end of day 3**, stop and fall back to a
  single VM + docker-compose managed by Terraform, then reinvest the saved time. A
  deployed simple thing beats an undeployed sophisticated thing, and the ADR explaining
  that call is worth more than the cluster.
* Keep the RRF fusion behind the `SearchService` interface with an application-level
  fallback implementation (~15 lines). It is cheap insurance against OpenSearch plugin
  or version surprises, and it keeps the retrieval work unblocked if the search tier
  misbehaves.

### Week 2 — Make retrieval pay for itself, then add RAG (40 h)

Goal by Friday: **a measured LLM-cost reduction and a working grounded assistant.**

| #   | Work                                                                                                                                                             | h   |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 2.1 | Evaluation harness + gold set (~100 labelled candidate–job pairs, bootstrapped by an LLM then hand-corrected). Baseline numbers for BM25-only, vector-only, RRF. | 10  |
| 2.2 | Embedding strategy: instruction-prefixed asymmetric embeddings per `docs/candidate-job-ranking.md`, batching, caching, re-embed triggers.                        | 6   |
| 2.3 | Retrieval-gated `build_pairs`: top-K per user, K configurable, feature-flagged so the old path can be re-enabled for A/B. Capture before/after cost and quality. | 8   |
| 2.4 | RAG assistant endpoint: retrieve → answer with citations, streaming, token budget, refusal when retrieval is empty. Single-turn only.                            | 10  |
| 2.5 | Performance pass: feed aggregation + indexes, keyset pagination, caching layer, load test (k6) with a documented before/after.                                   | 6   |

### Week 3 — Prove it, protect it, present it (40 h)

Goal by Friday: **an employer can click a link, see the system work, and read why it is built this way.**

| #   | Work                                                                                                                                                                                                                           | h   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 3.1 | Observability: `kube-prometheus-stack`, per-agent token/cost metrics, retrieval quality metrics, trace propagation through LangGraph nodes, 3 Grafana dashboards (product, pipeline cost, service health), 3 SLOs with alerts. | 9   |
| 3.2 | Autoscaling: HPA on the API (CPU + a custom queue/latency metric), load-test evidence of scale-out, `CronJob` or scale-to-zero for the pipeline worker.                                                                        | 4   |
| 3.3 | Argo Rollouts canary with `AnalysisTemplate` gated on the 3.1 latency SLO + a retrieval smoke check. Prove it by deploying a deliberately broken build and recording the automatic rollback.                                   | 7   |
| 3.4 | Thin demo UI: search with facets, result cards with fit scores, RAG chat with citations. Deployed via the same pipeline.                                                                                                       | 10  |
| 3.5 | ADRs (8–10, ~30 min each), README rewrite with the cost/quality numbers up front, architecture diagram, 5-minute demo script, teardown instructions.                                                                           | 8   |

The 3.3 rollback recording is the highest-value 30 minutes in the epic. "I have a
canary" is a claim; a 40-second clip of a bad build being detected and reverted
automatically is evidence, and it is the artifact most likely to get watched.

***

## 6. Decisions

### Settled

| #   | Decision     | Choice                                     | Rationale                                                                                                                                                                                                                                                                                                       |
| --- | ------------ | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Hosting      | **Small managed Kubernetes**               | Strongest signal, and HPA / Argo Rollouts / kube-prometheus-stack cover four requirements natively (see §3).                                                                                                                                                                                                    |
| 2   | Demo surface | **Thin React/Next UI** — search + RAG chat | A clickable URL is what a non-engineer screener judges. Budget 10 h, cut line #3 if behind.                                                                                                                                                                                                                     |
| 3   | Cost ceiling | **~$75/mo**                                | Enough for a real cluster; not enough for managed search, which forces decision 4 (happily).                                                                                                                                                                                                                    |
| 4   | Search tier  | **Self-hosted OpenSearch in-cluster**      | Decisive and verifiable: Elasticsearch's native `rrf` retriever is **Enterprise-licensed** and returns HTTP 403 on Basic. OpenSearch ships RRF (`score-ranker-processor`, 2.19+) and score normalization under Apache 2.0. Also fits the cost ceiling and adds a genuine StatefulSet/PVC/heap-tuning ops story. |
| 5   | CRD install  | **CI bootstrap script, not Terraform**     | Terraform plans against a schema it discovers before anything runs, so installing a CRD and using it in one apply is impossible. Rather than hide an imperative step inside a `null_resource`, Terraform stops at the cluster edge and a verified, idempotent script applies the Gateway API CRDs between the two stacks — which in turn lets `cluster-services` manage `GatewayClass`/`Gateway` as real resources. [ADR 0001](../adr/0001-gateway-api-crd-installation.md). |

Decision 4 is the single best ADR in the epic — a real constraint, discovered by
reading a licence table, with three named alternatives (pay for Enterprise, fuse in
application code, move to OpenSearch) and a defensible pick.

Decision 5 is the second-best, for a different reason: it is a *model* constraint
rather than a licensing one. "Why isn't this in Terraform?" invites explaining why
plan-then-apply cannot express a mid-apply schema change, why every workaround is
just a different way of manufacturing that phase boundary, and why upstream
(SIG-Network, Traefik, Envoy Gateway) all landed on the same imperative
`kubectl apply --server-side` rather than a chart. Six named alternatives, and the
pick is the cheap one on purpose.

### Proposed stack (to confirm on day 1)

| Layer          | Choice                                                                      | ~$/mo   |
| -------------- | --------------------------------------------------------------------------- | ------- |
| Cluster        | DigitalOcean DOKS (free control plane), 2 × 4 GB nodes                      | 48      |
| Load balancer  | DO LB + Ingress (nginx)                                                     | 12      |
| Search         | OpenSearch 2.19+ StatefulSet, k-NN plugin, in-cluster                       | 0       |
| Database       | MongoDB Atlas M0 free tier                                                  | 0       |
| Object storage | DO Spaces                                                                   | 5       |
| Registry       | DOCR (free tier)                                                            | 0       |
| Metrics/traces | kube-prometheus-stack in-cluster + OTel Collector → Grafana Cloud free tier | 0       |
| Deploys        | Argo Rollouts, canary gated on Prometheus analysis                          | 0       |
| **Total**      |                                                                             | **~65** |

In-cluster Prometheus is required regardless (HPA custom metrics and the rollout
analysis gate both query it), so Grafana Cloud is used only for dashboards and
retention. Alternative if cost matters more than hours: Hetzner + k3s via Terraform,
\~€25/mo, but a self-managed control plane is exactly the low-multiplier work §3 warns
about. Atlas M0's 512 MB limit needs a size check against the existing `jobs`
collection on day 1; fall back to a self-hosted StatefulSet or paid M10 if it is tight.

### Still open

1. **Embedding model.** Recommendation: start with a hosted API
   (`text-embedding-3-small`) so week 1 has no inference infrastructure, and let the
   eval harness (2.1) decide whether the asymmetric-retrieval problem described in
   `docs/candidate-job-ranking.md` actually costs measurable recall. Self-hosted
   instruction-prefix models (E5/BGE) become a *justified* follow-up only if the
   numbers say so — which is a much better interview answer than having self-hosted
   from the start on principle. Note the 4 GB nodes leave no room for local inference
   anyway.
2. **Public repo?** If yes, this is a day-1 blocker, not a week-3 tidy-up: `.env` is
   currently sitting in the working tree with live credentials. Rotate, scrub history,
   and move to sealed secrets or the cloud secret manager before the first push.

***

## 7. Cut lines (in order, if behind schedule)

The plan lands at 121 h against 120 h, so this list is the only slack. Cut from the top.

| #   | Cut                                                                              | Saves |
| --- | -------------------------------------------------------------------------------- | ----- |
| 1   | Cross-encoder reranking (stretch anyway)                                         | 0     |
| 2   | RAG streaming → plain JSON response                                              | 2 h   |
| 3   | Demo UI → search only, drop the chat surface                                     | 4 h   |
| 4   | Demo UI entirely → Grafana + recorded walkthrough                                | 10 h  |
| 5   | Canary → blue-green with manual promotion (still a real strategy, half the work) | 4 h   |
| 6   | Autoscaling → configured and documented, load-test evidence dropped              | 2 h   |

There is one more escape hatch, but it triggers early rather than late: **if the
cluster is not serving traffic by end of day 3, drop managed Kubernetes** for a single
VM + docker-compose under Terraform (§5, week 1). Taken on day 3 that reclaims ~12 h
and the whole plan still works. Taken in week 3 it reclaims nothing, because
HPA, Argo Rollouts and `kube-prometheus-stack` are load-bearing by then. This is the
one decision with a hard expiry date.

**Never cut:** the retrieval evaluation harness (2.1), the LLM cost metrics (3.1), and
the ADRs (3.5). Those three are the entire difference between a project that looks
impressive and a project that survives an hour of technical questions.

***

## 8. What "done" sounds like in an interview

The epic succeeds if these become true, specific, numeric answers.

| Question                                                   | The answer this epic produces                                                                                                                                                                                                              |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| "Tell me about a performance problem you solved."          | Cost curve was O(users × jobs) LLM calls; hybrid retrieval made it O(users × K); here is the measured reduction and the quality delta on a labelled eval set.                                                                              |
| "How do you know the search is good?"                      | Recall@K / nDCG on a gold set, per-configuration, in CI.                                                                                                                                                                                   |
| "Why OpenSearch and not Elasticsearch/pgvector/Qdrant?"    | Elasticsearch gates the `rrf` retriever behind an Enterprise licence (403 on Basic); OpenSearch ships RRF under Apache 2.0, in one system that also serves the user-facing feed. Three alternatives named, one constraint that decided it. |
| "How do you deploy safely?"                                | Canary gated on latency SLO and a retrieval smoke check, with an actual demonstrated rollback.                                                                                                                                             |
| "How do you know it's healthy?"                            | Three SLOs, dashboards, and the specific alert that fires first.                                                                                                                                                                           |
| "Where does Terraform stop, and why?"                      | At the cluster edge. Terraform plans against a schema fixed before execution, so a mid-apply CRD install cannot be expressed; the boundary is drawn where the tool's model breaks, not where it ran out of features. Six alternatives named, upstream agrees. |
| "Walk me through a trade-off you regret or would revisit." | Whatever the ADRs' "consequences" sections honestly record.                                                                                                                                                                                |

***

## 9. Deliverables checklist

* \[ ] `terraform/` — modules + environments, remote state, documented up/down
* \[ ] `scripts/bootstrap-cluster.sh` + `Makefile` up/down targets — CRD bootstrap and the documented apply order (ADR 0001)
* \[ ] `deploy/` — Helm chart or manifests, OpenSearch StatefulSet, HPA, Argo Rollouts spec
* \[ ] `.github/workflows/` — PR gate, CD, canary deploy with automatic rollback
* \[ ] `search/` or `retrieval/` — index management, hybrid query, RRF fusion
* \[ ] Embedding node in `orchestration/nodes/`, backfill script in `scripts/`
* \[ ] `benchmarks/retrieval/` — gold set, metrics, CI-runnable
* \[ ] RAG endpoint + citation contract
* \[ ] `observability/` — OTel config, dashboards as code, alert rules
* \[ ] `docs/adr/0001..000N` — one per real decision (0001 written: Gateway API CRD installation)
* \[ ] `ui/` — thin search + RAG chat frontend, deployed by the same pipeline
* \[ ] Load-test scripts + before/after results committed
* \[ ] README rewritten: what it does, the numbers, how to run it, how to tear it down
* \[ ] 5-minute demo script, plus a recorded clip of the canary auto-rollback
