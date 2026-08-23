# Week 1 study outline — infrastructure + search core

**Source of truth:** `docs/planning/flagship-demo-epic.md` §4–§7.
**Week 1 goal:** a public URL, deployed by CI, serving hybrid search.
**This document’s purpose:** a reading map, not an implementation plan. Use the *concepts / terms / decision points* under each task to pull official docs before coding.

Scope here is **Week 1 only** (tasks 1.1–1.7). Week 2 embeddings-as-strategy, retrieval-gated `build_pairs`, RAG, and Week 3 HPA / Argo Rollouts / kube-prometheus-stack are called out only where a Week 1 choice would paint you into a corner.

***

## How to use this

For each task: learn the **must-know** items until you can explain the **decision points** out loud. Then pull docs listed in [Documentation pull list](#documentation-pull-list). Skip stretch concepts unless a decision point forces them.

Hard constraint from the epic: **if the cluster is not serving HTTP traffic by end of day 3, drop DOKS** for a single VM + docker-compose under Terraform. That call expires; later weeks assume k8s primitives.

***

## Current baseline (what you are attaching to)

| Area | Today |
|---|---|
| Deploy | Single-stage `Dockerfile` (`python:3.12-slim`) running FastAPI only. Image tag `v*` → GHCR. No tests/lint in CI. No IaC, no cluster, no Ingress. |
| Runtime mismatch | `Dockerfile` is 3.12; `pyproject.toml` / `.python-version` require **≥3.13**. Must be resolved in 1.1/1.3. |
| Config / secrets | `Config` is a frozen Pydantic model over env vars; `python-dotenv` loads `.env` if present. `.gitignore` has `*.env`. Epic flags live credentials in the working tree — treat as a day-1 blocker if the repo will be public. |
| API | FastAPI + Auth0. `POST /jobs/search` is a Mongo aggregation over `assessments` with `$lookup` into `jobs` + `job_applications`. Skip pagination, sort after join. Filters: remote / source / tags (`$all`) / location regex / ATS floors / deal-breakers / application flags. **No free-text search.** CORS is `allow_origins=["*"]` + `allow_credentials=True`. |
| Pipeline | LangGraph: `collect → normalize → dedupe → persist_jobs → build_pairs → screen/assess/cover_letter`. `persist_jobs` upserts Mongo only. Worker entrypoint is `uv run run-pipeline` (`orchestration.runner`), **not** the API image CMD. |
| Storage | MongoDB (intended Atlas). S3-compatible object storage via boto3 (`S3_ENDPOINT_URL` already abstract — Spaces is a config change). |
| Logs | loguru to stdout + rotating files (`serialize=True` on files). No OTel. |
| Lint | `.flake8` + `.style.yapf`. Epic wants **ruff**. No mypy/pyright config. |
| Dead weight | `workers/job_processing.py` + `job_processing` / `failed_entries` collections. |

***

## 1.1 Confirm stack, Atlas size, secrets hygiene, cheap wins (~4 h)

**What you actually do**

- Confirm §6 stack (DOKS 2×4 GB, DO LB + nginx Ingress, in-cluster OpenSearch 2.19+, Atlas M0, Spaces, DOCR, Grafana Cloud later).
- Measure `jobs` (+ checkpoints, assessments, profiles) against Atlas M0’s 512 MB / connection limits.
- Rotate and remove live secrets from the tree; decide secret *injection* path for cluster + CI.
- Cheap wins: delete legacy worker; multi-stage Dockerfile, non-root, pinned digest, `.dockerignore`; fix CORS.

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **DOKS** (DigitalOcean Kubernetes Service) | Managed control plane (free) vs you-pay worker nodes. Control plane ≠ capacity. |
| **Node / node pool / droplet size** | 2×4 GB is the cost ceiling. Drives OpenSearch heap, API+worker packing, and “no local embedding model”. |
| **Control plane vs data plane** | You do not run etcd/API-server. You *do* size and drain workers. |
| **Atlas M0 free tier** | Storage cap, shared RAM, connection limits, no VPC peering on free. Size check is a go/no-go. |
| **Working-set vs on-disk size** | Mongo collection size ≠ Atlas billed storage (indexes, oplog, padding). Measure both. |
| **Secret vs ConfigMap** | Non-sensitive config (log level, index name) vs credentials (API keys, Mongo URI, Auth0). |
| **Sealed Secrets / External Secrets / cloud secret store / CI secrets** | Four different injection models. Pick one for k8s; GitHub Actions secrets are a second store. |
| **Credential rotation** | Assume `.env` leaked if it was ever committed or sitting unignored. Rotate OpenAI, Grok, Apify, Auth0, Mongo, S3. |
| **Public vs private repo** | If public, scrub is a *day-1* blocker (history rewrite), not a week-3 tidy. |
| **CORS credentialed requests** | `*` + `allow_credentials=True` is invalid/unsafe. Need explicit origins once a UI/public URL exists. |
| **Multi-stage image / distroless-ish runtime / non-root USER / digest pin / `.dockerignore`** | Current image `COPY . .` after `uv sync` can pull `.venv` and `logs`. Reviewers spot this immediately. |
| **Base image vs app Python version** | 3.12 image vs 3.13 requirement. Align before CI “just works”. |

### Decision points

1. **Atlas M0 stay / leave.** Stay, self-host Mongo StatefulSet, or pay M10. Self-hosting Mongo on 4 GB nodes competes with OpenSearch — almost certainly the wrong squeeze.
2. **Public repository?** If yes, secret scrub + history rewrite before first remote. If no, still rotate and stop committing `.env`.
3. **k8s secret injection:** sealed-secrets vs External Secrets Operator + DO/GitHub vs plain `kubectl create secret` (demo-ok, interview-weak) vs DO Container Registry/App secrets. Week 1 can be “Secrets as k8s objects, values from CI”, but name the target.
4. **CORS allowlist:** which origins (public hostname only? localhost for dev?).
5. **Image Python version:** 3.13 slim vs drop `requires-python` to 3.12. Do not leave the mismatch.
6. **Legacy worker:** delete in 1.1 (cheap win) vs leave until search dual-write is proven. Epic says delete.

***

## 1.2 Terraform: network, DOKS, LB, DNS, TLS, Spaces, registry, remote state (~12 h)

**What you actually do**

Stand up **one** live environment with remote state: VPC, DOKS cluster + node pool, Load Balancer + Ingress, DNS + TLS (cert-manager), Spaces bucket (app data *and/or* state), DOCR. Document `up` / `down`. Modules parameterized so a second env is a tfvars file, not a rewrite — you will not run a second cluster (cost).

This is the low-AI-multiplier, wall-clock-bound block. Get HTTP 200 from a placeholder or the API on a public hostname by **end of day 3**.

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **Terraform provider / resource / data source** | digitalocean, kubernetes, helm, kubectl. Know which layer owns which object. |
| **State file / remote backend / state locking** | Local state on a laptop is how you lose the cluster. Spaces (S3-compatible) or Terraform Cloud. Locking (Dynamo-style or native) prevents double-apply. |
| **Workspace vs separate state vs tfvars** | Epic wants one env + parameterized modules. Don’t invent workspaces unless you understand blast radius. |
| **Module vs root module** | Network, k8s, DNS, registry as modules; root wires them. |
| **VPC / subnet / region** | DOKS in a VPC; Spaces is regional; LB is regional. Same region or you pay latency + complexity. |
| **DOKS cluster + node pool** | Cluster create ≠ nodes. Autoscaling node pools exist; Week 1 can be fixed size. |
| **kubeconfig / token auth / `doctl kubernetes cluster kubeconfig`** | How Terraform Kubernetes/Helm providers talk to the cluster they just created (chicken-egg: providers need a live API). |
| **Terraform Kubernetes provider vs Helm provider vs `kubernetes_manifest`** | Who applies Ingress Controller, cert-manager, app chart. Mixing all three without a rule causes drift. |
| **Service `type: LoadBalancer` vs Ingress** | DO provisions a cloud LB per LB Service. Ingress **shares one LB** across hosts/paths. Epic: one DO LB (~$12) + nginx Ingress. |
| **Ingress Controller (ingress-nginx)** | Not the same as an Ingress *object*. Controller must be installed first. |
| **Layer-4 vs Layer-7 LB** | DO LB is L4 to the controller; nginx does HTTP routing, TLS terminate or passthrough. |
| **DNS A/AAAA vs CNAME, TTL** | Point hostname at LB. Cert issuance fails if DNS isn’t visible yet. |
| **cert-manager, ClusterIssuer / Issuer, Certificate** | ACME client in-cluster. |
| **Let’s Encrypt HTTP-01 vs DNS-01** | HTTP-01 needs a reachable Ingress on port 80. DNS-01 needs DO DNS API credentials. HTTP-01 is simpler if the LB is public. |
| **TLS terminate at Ingress vs passthrough** | Terminate at nginx for a demo. |
| **DO Spaces** | S3 API. Already matches `S3_ENDPOINT_URL`. Separate bucket for Terraform state vs app objects is normal. |
| **DOCR (DigitalOcean Container Registry)** | Free tier; image pull secrets for nodes (`imagePullSecret` / DOCR integration). |
| **IAM / API token scopes / least privilege** | Personal DO token in Terraform vs a narrowly scoped one. CI will need one too (or OIDC-equivalent if DO supports it for you). |
| **Destroy / teardown** | PVC, LB, DNS, Spaces objects, and state backend all have destruction order and “prevent_destroy” traps. Epic requires a demonstrated teardown. |

### Decision points

1. **Terraform state backend:** Spaces bucket vs Terraform Cloud vs local (reject local). Who creates the state bucket (bootstrap stack vs click-ops once)?
2. **How Terraform reaches the cluster after create:** `digitalocean_kubernetes_cluster.kube_config` interpolation vs separate `terraform apply` stages vs `doctl`. Nested providers are a classic footgun — read this before writing HCL.
3. **What Terraform owns vs what Helm/CI owns.** Typical split: Terraform = VPC, DOKS, node pool, DOCR, Spaces, DNS zone, maybe Ingress Controller + cert-manager. CI = app Helm release. Draw this line on day 1.
4. **Ingress Controller:** ingress-nginx (Helm) vs DO’s Kubernetes-native LB annotations only. Epic says nginx.
5. **DNS zone:** DigitalOcean Domains vs existing registrar with CNAME only. ACME HTTP-01 vs DNS-01 follows from this.
6. **Hostname / path:** apex vs `api.` subdomain vs path prefix. Current Dockerfile uses `--root-path /job-aggregator/api` — that **root path must match** Ingress path and FastAPI `FASTAPI_ROOT_PATH`, or auth redirects and OpenAPI break.
7. **Region:** FRA/AMS vs other. Latency to Atlas + Spaces + you.
8. **Day-3 fallback trigger:** what “serving traffic” means (any 200 vs authenticated API vs OpenSearch). Define the test *before* day 3.

***

## 1.3 Helm/manifests: API, pipeline worker, OpenSearch StatefulSet (~6 h)

**What you actually do**

Package three workloads: **API Deployment**, **pipeline worker** (Deployment or CronJob — Week 1 can be a long-running loop matching `PIPELINE_SCHEDULE_SECONDS`), **OpenSearch StatefulSet** with PVC, heap settings, and k-NN plugin. Health probes, requests/limits that fit 2×4 GB, env from Secrets.

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **Workload kinds:** Deployment, StatefulSet, Job, CronJob | API = Deployment. OpenSearch = StatefulSet (stable identity + volume). Worker = Deployment (sleep loop) or CronJob (12 h). |
| **Pod vs container vs replica** | One pod can run one container. Don’t hide API+worker+OpenSearch in one pod. |
| **StatefulSet ordinal identity / headless Service** | `opensearch-0.opensearch.svc…` — required for clustering even if you run **one replica**. |
| **PersistentVolume / PVC / StorageClass** | DO Block Storage. Reclaim policy, size, `ReadWriteOnce`. Delete PVC on teardown or you keep paying. |
| **Heap (JVM) vs container memory limit** | OpenSearch rule of thumb: heap ≈ 50% of container RAM, cap ~32 GB, **leave room for off-heap/k-NN**. On a 4 GB node this is the tightest packing problem in Week 1. |
| **k-NN plugin / `knn_vector` / HNSW** | Must be in the image (`opensearchproject/opensearch` includes it on 2.x, but confirm version **2.19+** for RRF `score-ranker-processor`). |
| **Security plugin / demo certs / `DISABLE_SECURITY_PLUGIN` / `plugins.security.disabled`** | Default OpenSearch images often enable security and then fail probes. For a private in-cluster demo, disabling or a minimal internal user is a real choice with interview consequences. |
| **Resource requests vs limits / QoS (Guaranteed/Burstable)** | Over-request → Pending pods on 4 GB nodes. Under-limit → OOMKilled. |
| **liveness / readiness / startup probes** | OpenSearch needs a long startup probe. Don’t liveness-kill it while it allocates heap. |
| **ConfigMap vs Secret vs env vs mounted file** | `opensearch.yml`, `jvm.options`, app env. |
| **Helm chart vs raw YAML vs Kustomize** | Chart values for env-specific bits (image tag, hostname, replica count). |
| **imagePullSecret / DOCR k8s integration** | Private registry: nodes must authenticate. |
| **Two processes, two images or one image two commands** | Same image, different `command:` (FastAPI vs `run-pipeline`) is the obvious split. Dockerfile today only has the API CMD. |
| **In-cluster DNS names** | App talks to `opensearch.opensearch.svc.cluster.local:9200` and Atlas as an *external* hostname (not in-cluster). |
| **NetworkPolicy** | Out of epic scope. Don’t spend Week 1 here. |

### Decision points

1. **OpenSearch replica count:** 1 (fits budget, no HA, honest ADR) vs 2 (won’t fit 2×4 GB with API+worker). Default: **1 replica**, document the trade-off.
2. **Node packing:** dedicated node for OpenSearch vs co-locate with API. Co-location risks noisy neighbor; dedicated may leave the API node idle. Need a memory budget spreadsheet (node RAM − kube-system − OpenSearch − API − worker).
3. **OpenSearch security:** disabled on a private ClusterIP vs internal basic auth. Never expose 9200 via Ingress.
4. **Worker schedule:** keep the in-process sleep loop vs Kubernetes CronJob. CronJob is cleaner on k8s but changes `orchestration.runner`. Week 1 can keep the loop to save hours.
5. **Helm vs manifests.** Helm if you already owe values for image tag from CI. Raw YAML is faster to first deploy; you’ll likely wrap it anyway for 1.4.
6. **PVC size** for OpenSearch: index of `jobs` + knn vectors + translog. Start small (10–20 GiB) and document.
7. **OpenSearch version pin:** **2.19+** is load-bearing (RRF processor). Pin a digest, not `latest`.

***

## 1.4 CI gate + CD on merge to main (~6 h)

**What you actually do**

Replace tag-only GHCR publish with: PR pipeline (ruff, type check, unit tests, integration tests against **service containers**, image build) → on merge to `main`, push image to **DOCR** and deploy to the cluster (Helm upgrade / kubectl).

Canary/Argo Rollouts is **Week 3**. Week 1 CD can be a straight Helm upgrade as long as it is automatic and reversible (`helm rollback`).

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **GitHub Actions workflow / job / step / `services:`** | `services:` can run Mongo + OpenSearch beside the job for integration tests. |
| **PR gate vs CD workflow** | Gate must not need cluster credentials. CD must. |
| **OIDC federation vs long-lived DO token** | Prefer OIDC if usable with DOCR/DO API; otherwise a scoped token in GitHub Secrets. |
| **Buildx / provenance / SBOM** | Optional. Getting a tagged image to DOCR is the Week 1 bar. |
| **Image tag strategy** | `git sha` (immutable, CD-friendly) vs semver vs `latest` (avoid). |
| **ruff** (lint + format) vs existing flake8/yapf | One tool. Don’t run both. |
| **Type checker:** mypy vs pyright vs ty | Pick one; add a baseline so the first CI run isn’t 400 errors. |
| **pytest markers / `--run-priced`** | Priced tests stay off in CI. Integration tests must not need Apify/OpenAI. |
| **Testcontainers vs GHA `services:` vs “talk to Atlas”** | CI should not use production Atlas. Local Mongo+OpenSearch containers. |
| **`uv sync --frozen` / `uv run`** | Reproducible CI matching local. |
| **kubeconfig in CI / `doctl` / `helm upgrade --install`** | Auth to DOKS from GitHub. Namespace, wait-for-ready, timeout. |
| **Branch protection / required checks** | CD on merge is meaningless if main can be pushed around the gate. |
| **GHCR vs DOCR** | Today: GHCR on `v*` tags. Target: DOCR for cluster pull (same region, no GitHub pull-rate/auth mess). Decide whether GHCR remains for public artifacts. |

### Decision points

1. **Integration test topology:** GitHub `services:` (Mongo, OpenSearch) vs compose on the runner vs skip OpenSearch tests until 1.6. Don’t hit live Atlas/OpenSearch from PRs.
2. **Type-check strictness:** clean slate vs `type: ignore` baseline. Budget is 6 h including CD — a baseline is allowed.
3. **CD mechanism:** `helm upgrade` from GitHub vs Terraform applying the Helm release vs Argo CD (explicitly **out of scope**).
4. **Where CD credentials live** and how kubeconfig is produced.
5. **What “deploy on merge” deploys in Week 1:** API only vs API+worker vs also OpenSearch (OpenSearch should be Terraform/Helm once, not every commit).
6. **Keep GHCR workflow?** Delete, or keep tags as a release artifact. Avoid two source-of-truth registries for the cluster.

***

## 1.5 Minimal telemetry: OTel + queryable structured logs (~3 h)

**What you actually do**

Enough to debug the rest of the epic: OpenTelemetry **auto-instrumentation** for FastAPI and pymongo; structured logs you can actually query. Full kube-prometheus-stack, SLOs, and LLM-cost metrics are **Week 3**. In-cluster Prometheus is still the long-term destination (HPA + canary analysis query it), so don’t pick an exporter that you must throw away.

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **Traces / metrics / logs** (the three signals) | Week 1: traces + structured logs. Metrics can be thin. |
| **Span / trace ID / context propagation / W3C `traceparent`** | Request → Mongo → (later) OpenSearch must share a trace. |
| **OTel auto-instrumentation vs SDK** | `opentelemetry-instrument` wrapping uvicorn vs manual spans. Auto is the 3 h path. |
| **OTLP exporter / OTel Collector** | Apps should export OTLP to a Collector, not directly to a vendor SDK. |
| **Instrumentation libraries:** FastAPI, pymongo, httpx/aiohttp | Cover API + Mongo now; OpenSearch client and LangGraph later. |
| **Resource attributes** (`service.name`, `k8s.pod.name`) | How you filter “API vs worker”. |
| **Structured logging** | loguru `serialize=True` is JSON-on-disk today; in k8s you want **JSON on stdout** (files in the container are a dead end). |
| **stdout/stderr log model / Grafana Loki / Grafana Cloud** | Queryable = shipped somewhere. Epic: Grafana Cloud free tier for dashboards/retention; Week 3 adds in-cluster Prometheus. |
| **Correlation:** inject `trace_id` into log records | Otherwise traces and logs don’t join. |

### Decision points

1. **Log sink for Week 1:** Grafana Cloud (Loki/OTLP) vs `kubectl logs` only (not “queryable”) vs cheap in-cluster Loki. Epic leans Grafana Cloud.
2. **Collector in-cluster now vs Grafana Cloud OTLP endpoint directly.** Collector is the shape you want for Week 3; a vendor endpoint is faster. Prefer Collector if the Helm add is small.
3. **Keep loguru vs stdlib/OTel logging.** Adapting loguru to JSON+trace fields is less work than a rewrite — but drop file sinks in the container.
4. **What gets auto-instrumented in the worker** (LangGraph is not free). Week 1 bar is API + pymongo; worker JSON logs with `cycle_id` (already present) may be enough.

***

## 1.6 Search index: mapping, analyzers, synonyms, dual-write, backfill (~6 h)

**What you actually do**

Create an OpenSearch index over `jobs`: BM25 on title / description / tags, `knn_vector` field, synonym dictionary (`k8s` → `kubernetes`, etc.). Dual-write from `persist_jobs`. Backfill script for existing Mongo jobs.

**Week 1 embedding model:** hosted API (`text-embedding-3-small` recommended) so you do not run inference on 4 GB nodes. Instruction-prefix E5/BGE is a Week 2 eval decision, not a Week 1 blocker — but the **vector dimension and space type in the mapping are expensive to change**, so pick a dimension now.

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **Index / mapping / settings vs aliases** | Mapping changes often mean reindex. Alias (`jobs` → `jobs-v1`) lets you rebuild without downtime. |
| **Analyzer / tokenizer / token filter / normalizer** | `standard` vs `english` stemmer on descriptions; **keyword** or `normalizer` on tags. |
| **Synonym graph filter** (`synonym_graph`) at index vs query time | Index-time: faster queries, reindex on dict change. Query-time: flexible, slightly slower. Tags want canonicalization. |
| **BM25** (`similarity` module) | Keyword relevance for title/description/tags. Default in OpenSearch/Lucene. |
| **`knn_vector` field, dimension, `space_type` (cosinesimil / l2 / innerproduct)** | Must match the embedding model. Cosine vs inner product depends on whether vectors are normalized. |
| **HNSW parameters** (`m`, `ef_construction`, `ef_search`) | Recall vs memory vs latency. Defaults are fine for a jobs corpus; know they exist. |
| **Lucene k-NN vs nmslib/faiss engines** (OpenSearch k-NN plugin) | 2.x default engine has shifted toward Lucene. Confirm what 2.19+ uses for `knn_vector`. |
| **Dual-write** | Same node writes Mongo then OpenSearch. Failure/ordering: Mongo-success / OS-fail needs retry or the backfill is the safety net. |
| **Idempotent upsert** | Document `_id` = `job.uid`. Re-persist must overwrite, not duplicate. |
| **Backfill / reindex / scroll or PIT** | Read Mongo in batches, embed, bulk index. Rate-limit the embedding API. |
| **Bulk API / `_bulk`** | Don’t index one-by-one on backfill. |
| **Asymmetric retrieval / instruction prefixes** | Design in `docs/candidate-job-ranking.md`. Week 1 can embed `description_raw` (the design’s own “baseline to validate first”). Don’t explode the mapping into role/experience fields yet. |
| **Existing tag canonicalization** | Tags are already lower-cased. Synonyms are the remaining gap (`k8s`/`kubernetes`). Don’t confuse with the title/company normalization agent. |

### Decision points

1. **Embedding model and dimension** (locks the mapping). `text-embedding-3-small` (1536 dims) vs `-large` (cost/latency) vs a 384-dim MiniLM (cheaper k-NN RAM). Epic recommendation: **3-small**, eval in Week 2.
2. **What text you embed in Week 1:** `description_raw` (+ title) vs structured fields you don’t have yet (enrichment is stretch). Follow the ranking doc’s baseline.
3. **Synonyms: index-time vs query-time vs both.** Tags: canonical dict at index. Query: same dict so user-typed `k8s` matches.
4. **Dual-write error handling:** fail the pipeline node (retry via LangGraph) vs log-and-continue + periodic backfill. Failing the node is safer for “index is source of retrieval truth”.
5. **Index name / alias scheme** now, even with one index.
6. **Where OpenSearch client config lives:** new env vars (`OPENSEARCH_HOST`, credentials) on `Config`.
7. **HTML in `description_raw`:** strip to text before BM25 + embeddings, or index raw. Raw HTML pollutes tokens.

***

## 1.7 Hybrid query + RRF search pipeline, `SearchService`, wire `POST /jobs/search` (~5 h)

**What you actually do**

Implement hybrid retrieval (BM25 + kNN) fused with OpenSearch **search pipeline** `score-ranker-processor` (RRF). Hide it behind a `SearchService`. Wire **free-text** into `POST /jobs/search` **without dropping** existing score/filter/pagination semantics.

Keep an **application-level RRF fallback** (~15 lines) behind the same interface — insurance against plugin/version surprises.

### Must-know concepts / terms

| Term | Why it matters here |
|---|---|
| **Hybrid query** (OpenSearch `hybrid` / combination query) | Two result lists (lexical + vector), then fuse. |
| **Search pipeline / request vs response processor** | Server-side chain. RRF lives here in the chosen design. |
| **`score-ranker-processor` / RRF (`rank_constant`)** | Reciprocal Rank Fusion: `1 / (k + rank)`. Rank-based, so BM25 scores and cosine scores need not be normalized together. Requires **2.19+**. |
| **Score normalization vs RRF** | Normalization (min-max) is the alternative; RRF is the ADR. Know why you didn’t min-max. |
| **Why not Elasticsearch `rrf` retriever** | Enterprise-licensed; 403 on Basic. This is the epic’s flagship ADR — be able to state it. |
| **Query-time analyzer / `multi_match` / `term` vs `match` on tags** | Tags: exact/synonym. Title+description: full-text. |
| **kNN query vs `hybrid` subquery** | `knn` on `knn_vector` using the **query embedding** (one embedding API call per search). |
| **Filter context vs query context** | `remote`, `source`, `tags`, `location` should be **filters** (yes/no, no scoring) so they combine with hybrid retrieval. |
| **Faceted search** | Aggregations for counts by source/tag/etc. Epic says `POST /jobs/search` gains facets; define the response shape. |
| **Hydration / join back to Mongo** | OpenSearch holds jobs (+ vectors). Fit scores and application status still live in Mongo. Pattern: retrieve job UIDs from OS → fetch assessments/status from Mongo (or vice versa). This is the real API design problem in 1.7. |
| **Pagination: `from`/`size` vs `search_after` vs current skip** | Skip-based pagination stays acceptable for Week 1 (performance pass is Week 2). Don’t promise keyset yet. |
| **`SearchService` as an interface** | Methods: `index_job`, `search(query, filters, k)`. Implementations: OpenSearch hybrid, in-process RRF fallback (two OS queries or OS BM25 + OS kNN, fuse in Python). |
| **Existing feed is assessment-centric** | Today the feed *starts from assessments* (jobs without a fit score do not appear). Hybrid search over `jobs` can surface unassessed jobs. **Product decision**, not just a plumbing one. |

### Decision points

1. **Feed semantics:** (A) hybrid search over jobs, then left-join assessments (new jobs visible, fit nullable); (B) hybrid search but only UIDs that already have an assessment (preserves today’s feed); (C) two modes (`q` present → corpus search; no `q` → old feed). Epic: “existing score/filter semantics are preserved” **and** “real full-text search”. C is the usual resolution.
2. **Where fusion runs:** OpenSearch pipeline (primary) vs Python RRF (fallback). Interface must not leak which one ran.
3. **Query embedding path:** embed the raw `q` string with the same model as documents. Instruction prefixes deferred to Week 2 unless cheap to add now.
4. **AuthZ:** search is still per-user (Auth0). Filters on application status are user-scoped and **cannot** be answered by OpenSearch alone — Mongo (or a denormalized user index) remains in the path.
5. **Facet payload:** new fields on `PaginatedDataResponse` vs a side object. Don’t break existing clients if there are none; still keep the Pydantic models honest.
6. **Empty `q`:** must not call the embedding API; fall back to current Mongo feed.

***

## Day-3 fallback (escape hatch, not a stretch)

**Trigger:** no public HTTP 200 from *your* LB/Ingress by end of day 3.

**Move to:** one VM + docker-compose, all still applied by Terraform (droplet, firewall, DNS, maybe Caddy/nginx for TLS). OpenSearch as a compose service with a volume. CI deploys via SSH or `docker compose pull && up`.

### Extra concepts if this fires

- Droplet / cloud-init / firewall / floating IP
- Compose `depends_on` vs actual readiness
- Caddy or nginx reverse proxy + Let’s Encrypt on a VM
- Why this ADR is *better told* than an unfinished cluster (epic §5, §7)

Do **not** keep investing in DOKS past the trigger “because it’s almost working”.

***

## Cross-cutting decision log (settle these; they span tasks)

| # | Decision | Suggested default from epic | Locked by |
|---|---|---|---|
| D1 | Hosting | DOKS, fall back to VM on day 3 | 1.2 |
| D2 | Search product | In-cluster OpenSearch 2.19+ | 1.3 / 1.7 |
| D3 | Embedding model (Week 1) | Hosted `text-embedding-3-small` | 1.6 mapping |
| D4 | Public repo | Open — **blocker if yes** | 1.1 |
| D5 | Atlas M0 | Stay if size check passes | 1.1 |
| D6 | Terraform vs Helm ownership | TF: cloud+cluster+ingress/cert-manager; Helm: app+OpenSearch | 1.2 / 1.3 |
| D7 | API root path vs hostname | Prefer `https://<host>/` with `FASTAPI_ROOT_PATH=""` over `/job-aggregator/api` | 1.2 / 1.3 |
| D8 | Unassessed jobs in search | Split path: `q` → OS corpus; no `q` → Mongo feed | 1.7 |
| D9 | Secret injection | CI → k8s Secret; rotate everything in 1.1 | 1.1 / 1.4 |

***

## Documentation pull list

Grouped by task. Pull **official** docs first; treat blog posts as secondary. Versions in parentheses are the ones the epic assumes.

### 1.1 — platform limits, secrets, image, CORS

- DigitalOcean: DOKS product limits; droplet/node sizes and pricing; DOCR free-tier limits.
- MongoDB Atlas: M0 (Free) limitations — storage, connections, available regions, no VPC peering.
- FastAPI / Starlette: CORSMiddleware, credentialed requests, `allow_origins`.
- Docker: multi-stage builds; `USER` non-root; pinning by digest; `.dockerignore`.
- Python images: official `python:3.13-slim` vs current 3.12 Dockerfile.
- Kubernetes: Secrets vs ConfigMaps (concepts). Optional: Bitnami Sealed Secrets **or** External Secrets Operator — only after D9.

### 1.2 — Terraform + DigitalOcean + Ingress + TLS

- Terraform: state backends (S3-compatible); state locking; modules; provider configuration; **configuring the Kubernetes provider with a cluster created in the same apply** (known-issue / two-phase apply).
- Terraform DigitalOcean provider: `digitalocean_vpc`, `digitalocean_kubernetes_cluster`, `digitalocean_kubernetes_node_pool`, `digitalocean_container_registry`, `digitalocean_spaces_bucket`, `digitalocean_domain` / records, `digitalocean_loadbalancer` (only if you manage LB outside Ingress).
- DOKS: getting kubeconfig; integrating with DOCR (node pull).
- Ingress-nginx Helm chart: Service `type: LoadBalancer`; proxy body size; `ingressClassName`.
- cert-manager: ClusterIssuer; Let’s Encrypt HTTP-01 on Ingress; rate limits (use staging issuer first).
- DigitalOcean DNS + Let’s Encrypt HTTP-01 requirements (port 80).
- DigitalOcean Spaces as Terraform backend (S3 protocol, endpoint, `use_lockfile` / locking options).

### 1.3 — k8s workloads + OpenSearch on small nodes

- Kubernetes: Deployment, StatefulSet, headless Service, PVC, StorageClass, probes, requests/limits, QoS.
- DigitalOcean: Block Storage CSI, reclaim policy, default StorageClass.
- Helm: chart layout (`Chart.yaml`, `values.yaml`, templates); `helm upgrade --install`.
- OpenSearch 2.19+ Docker image: env vars, disabling/enabling security plugin, JVM heap (`OPENSEARCH_JAVA_OPTS`), memory locking.
- OpenSearch k-NN plugin: `knn_vector` mapping; HNSW; Lucene engine notes for 2.19.
- OpenSearch: production-ish guidance on heap vs container RAM (even for a 1-node demo).
- OpenSearch: HTTP health (`/_cluster/health`, `/_cluster/health?wait_for_status=yellow`) for probes.

### 1.4 — GitHub Actions + uv + ruff

- GitHub Actions: `pull_request` / `push` to main; `services:` (Mongo, OpenSearch images); GITHUB_TOKEN vs explicit secrets; environments.
- docker/build-push-action + login to **DOCR** (not only GHCR).
- DigitalOcean: `doctl` auth from CI; `doctl registry login`; `doctl kubernetes cluster kubeconfig save`.
- uv: `uv sync --frozen`, running ruff/pytest via `uv run`.
- ruff: migrate from flake8 + yapf.
- mypy or pyright: incremental adoption (`ignore_missing_imports`, baseline).
- Helm: non-interactive `upgrade --install --wait --atomic` from CI.

### 1.5 — OpenTelemetry + logging in k8s

- OpenTelemetry: traces vs logs; OTLP; Collector (deployment vs sidecar — pick deployment).
- OpenTelemetry Python: auto-instrumentation; FastAPI; Pymongo; running as `opentelemetry-instrument uvicorn ...`.
- Grafana Cloud: OTLP ingest; free-tier limits (this is Week 1’s query UI).
- Kubernetes logging architecture: stdout, one JSON object per line.
- loguru: JSON serialization; intercepting stdlib logging; injecting extra fields (`trace_id`).

### 1.6 — OpenSearch indexing

- OpenSearch: mappings, explicit vs dynamic; text vs keyword; analyzers; synonym / synonym_graph filters.
- OpenSearch: index aliases; reindex API; bulk API.
- OpenSearch k-NN: field mapping (`dimension`, `method`, `space_type`); ingest of vectors.
- OpenAI embeddings API: `text-embedding-3-small` dimensions, batching, token limits (for the backfill).
- OpenSearch Python client (`opensearch-py`): sync vs async, bulk helpers.
- Project: `docs/candidate-job-ranking.md` (asymmetric retrieval, BM25 on tags, RRF, “baseline first”).
- Project: `orchestration/nodes/batch.py` `persist_jobs`; `models/collection_service.py` `JobPosting`.

### 1.7 — hybrid query, RRF, API wiring

- OpenSearch 2.19: **search pipelines**; **score-ranker-processor**; hybrid query syntax for your exact minor version (this moved between releases — read the version you pin).
- OpenSearch: filter context; `bool.filter`; kNN combined with filters (`post_filter` vs `filter` in knn — they are not the same).
- RRF: original paper-level intuition is enough (`1/(k+rank)`); `rank_constant`.
- Elasticsearch docs on `rrf` retriever **licensing** (to write the ADR, not to implement ES).
- Project: `api/routes/jobs.py`, `models/jobs_api.py` `JobFeedQuery`, `repository/mongo_jobs_repository.py` `_build_job_feed_pipeline`.

### Day-3 fallback only

- Terraform DigitalOcean droplet + firewall + reserved IP.
- docker-compose: healthchecks, restart policies, named volumes.
- Caddy automatic HTTPS **or** nginx + certbot on a VM.

***

## Suggested reading order (matches the day-3 gate)

1. **1.1 + 1.2 concepts** until you can draw: VPC → DOKS → Ingress Controller → cert-manager → DNS, and say where Terraform state lives.
2. **1.3 OpenSearch-on-small-nodes** (heap, PVC, security plugin, 2.19+ RRF) — this is what usually blows the memory budget.
3. **1.4** just enough to push an image and `helm upgrade` (you can deepen lint/types after first deploy).
4. **1.6 mappings + dual-write** in parallel with first cluster bring-up if 1.2 is in apply-wait loops.
5. **1.7 hybrid + SearchService + feed join** once a local or in-cluster OpenSearch answers `_cluster/health`.
6. **1.5** as soon as the API is reachable, not before — otherwise you have no traffic to look at.

***

## Out of Week 1 (do not rabbit-hole)

These have their own later tasks. Learn them only enough to avoid a conflicting Week 1 choice:

- Argo Rollouts, AnalysisTemplate, canary weights (needs Prometheus — Week 3).
- HPA, custom metrics adapter, scale-to-zero (Week 3).
- kube-prometheus-stack, SLO math, LLM token cost metrics (Week 3).
- Retrieval eval (Recall@K, nDCG, gold set) (Week 2).
- Instruction-prefix embedding models, cross-encoder rerank, description enrichment (Week 2 / stretch).
- GitOps / Argo CD / service mesh / multi-region (explicitly out of epic).
