# Hybrid Search & Retrieval Evaluation — Implementation Plan

**Status:** Ready for implementation
**Last updated:** 2026-09-06
**Open questions:** 0
**Epic:** [epic-02-hybrid-search-retrieval-eval.md](./epic-02-hybrid-search-retrieval-eval.md)

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done).

---

## Problem

The pipeline's pair fan-out is a Cartesian product of this cycle's unique jobs and every registered user (`build_pair_list` in `orchestration/state.py:75`). At the epic's planning numbers (500 new jobs/day × 50 users) that is 25,000 screening LLM calls per cycle. The helper is implemented and unit-tested; the live graph currently **does not use it** — `build_pipeline_graph` (`orchestration/graph.py:57-67`) wires `persist_jobs → END` and leaves `build_pairs` / `pair_pipeline` commented out (commit `11e9df1`, “temporarily exclude pricy nodes”). The cost curve was designed-in and paused. Q1 resolves that the pair subgraph will be re-enabled in this epic, wired together with top-$K$ hybrid retrieval gating to permanently cut the pair fan-out to $O(\text{users} \times K)$.

The user-facing job list is not a raw job board. `POST /jobs/search` (`api/routes/jobs.py:18`) is a personalized **assessed-job feed** showing positions deemed fitting for the authenticated user with their ATS scores. Currently, this relies on a heavy Mongo aggregation over `assessments` with `$lookup` into `jobs` and `job_applications` followed by post-join facet sorting (`repository/mongo_jobs_repository.py:351-517`). This is slow and cannot perform BM25 text search, stemming, or fast faceting.

Decisions Q2 and Q13 resolve this by establishing a **two-index OpenSearch architecture** with denormalized assessments:
1. OpenSearch `jobs` index: Global corpus of unique postings with 1536-d dense vectors (`text-embedding-3-small`), used for the ingestion pipeline's top-$K$ initial retrieval gate, offline retrieval benchmarks, and future RAG.
2. OpenSearch `assessments` index: Self-contained assessment records scoped to `username` with nested `job` and `status` objects. This allows `POST /jobs/search` to run entirely within OpenSearch in a single sub-50ms query, supporting both structured ATS/status filters and BM25 keyword matching (`q`) across technology, employer, and title, while eliminating Mongo lookups entirely.

Compose already runs OpenSearch 2.19 (`docker-compose.yml:21-48`) and `Config` already declares `OPENSEARCH_*` (`config.py:78-84`). There is no OpenSearch client, no index bootstrap, and `opensearch-py` is not in `pyproject.toml`.

Without a gold retrieval set, ranking changes stay anecdotal. Existing benchmarks (`benchmarks/screening/`, `benchmarks/fit_assessment/`) measure agent classification against historical ATS bands; they do not measure whether the right jobs were retrieved in the first place.

---

## Scope

### In scope

- OpenSearch `jobs` index: BM25 analyzers for `title` and HTML-stripped `description_raw` (tags explicitly excluded per Q3) + 1536-d k-NN vector field (`text-embedding-3-small` per Q4); index bootstrap from the running 2.19 compose node.
- OpenSearch `assessments` index: Denormalized assessment documents (`username`, ATS scores, deal breakers, summary, nested `job` snapshot, nested `status`) for sub-50ms candidate feed queries (decided in Q2/Q13).
- A `SearchService` managing both indices: global corpus search (BM25, vector, hybrid RRF for pipeline gating and benchmarks) and user feed queries (structured filters + BM25 keyword search `q`).
- `embed_jobs` LangGraph node after `persist_jobs`, plus a historical backfill script (`scripts/backfill_job_embeddings.py`).
- Retrieval-gated `build_pairs`: top-$K$ jobs per user instead of Cartesian product, re-enabling the pair subgraph (decided in Q1).
- Assessed-feed migration: update `POST /jobs/search` to query OpenSearch `assessments` directly with keyword search `q` (technology, employer, title), eliminating MongoDB `$lookup`s and keeping offset pagination intact.
- MongoDB denormalization & sync: store nested `job` and `status` in Mongo `assessments`; sync status changes to OpenSearch on `PATCH /jobs/{job_uid}/status`; migration script (`scripts/migrate_denormalized_assessments.py`).
- Offline retrieval harness under `benchmarks/retrieval/` (Recall@K, nDCG@K, MRR) comparing BM25 / vector / hybrid across the corpus.
- CI smoke of that harness: tiny frozen split (~10 queries) running against an OpenSearch CI container, failing on regressions (decided in Q9).
- Structured search latency + pipeline pair-count telemetry that Epic 3 can later scrape; not Grafana/Prometheus dashboards (those are Epic 3).
- Frontend coordination: Author a dedicated implementation plan for the client UI (`docs/planning/client-search-ui-implementation-plan.md`) specifying the keyword search input (`q`), filter panel integration, and API contract consumption; backend changes in this repo provide the documented API and contract tests (decided in Q12).

### Out of scope

- Direct modifications to client code in `react-app/` within this repository (managed in its respective UI repository/project environment per Q12; planned separately via `client-search-ui-implementation-plan.md`).
- Seniority structured facet/filter (omitted for v1 per Q10; seniority is supported via full-text keyword search `q`).
- Description enrichment / seniority extraction as a new pipeline agent (`docs/candidate-job-ranking.md` calls this out as a later quality lever).
- Cross-encoder / LLM rerank stage (ranking doc's "stage 2"; fit assessment already plays that role on retrieved pairs).
- Prometheus exporter, Grafana dashboards, SLOs — Epic 3.
- RAG assistant (`POST /rag/query`) — Epic 3, which consumes this search tier.
- Helm/K8s OpenSearch packaging — Epic 4.
- Changing screening / fit-assessment agent prompts or semantics.
- Migrating cover letters into OpenSearch (they remain in S3 / Mongo storage).

---

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| OpenSearch already in compose | `docker-compose.yml:21-48` — `opensearchproject/opensearch:2.19.0`, security plugin off, 512MB heap, healthcheck on `:9200` | Infra prerequisite from Epic 1 is met locally. No client, no index, no `readyz` ping. |
| OpenSearch config, unused | `config.py:78-84` — `OPENSEARCH_HOST/PORT/USE_SSL/VERIFY_CERTS/USER/PASSWORD/INDEX_NAME` (`jobs`) | Do not invent new env names; wire a client to these. `opensearch-py` is **not** in `pyproject.toml`. Hatch wheel currently packages only `scripts` and `orchestration` (`pyproject.toml:50-51`) — a new `search/` package must be added there. |
| Pair map disabled on purpose | `11e9df1` “temporarily exclude pricy nodes” | Resolved in Q1: pair map and top-$K$ gating are re-enabled together in this epic. |
| Cartesian pair builder | `orchestration/state.py:75-81` `build_pair_list(usernames, jobs)` | Tested in `tests/unit/test_pipeline_routing.py:93-108`. Gating replaces this helper or wraps it; downstream `Send` payload shape `{username, job_uid, job}` stays so pair nodes do not change. |
| `build_pairs` node | `orchestration/nodes/batch.py:136-150` | Loads **this cycle's** `unique_jobs`, not the full `jobs` collection. Resolved in Q5: hybrid search in OpenSearch is filtered strictly to this cycle's UIDs so candidates are evaluated against the newly collected batch. |
| Graph wiring | `orchestration/graph.py:37-70` | Pair subgraph is implemented (`build_pair_subgraph`) but disconnected. `persist_jobs → END` since `11e9df1`. Resolved in Q1: re-connect pair subgraph once `embed_jobs` and gated `build_pairs` are implemented. |
| Pair nodes | `orchestration/nodes/pair.py` | Idempotent on `(username, job_uid)` screening/assessment/cover-letter keys. Re-retrieving an already-screened job is cheap in LLM terms, wasted in graph fan-out. |
| `PipelineDeps` | `orchestration/deps.py:22-34` | No search or embedding client. New deps belong here, constructed in `build_deps`. |
| Failed-task vocabulary | `models/failed_tasks.py:8-16` `NodeName` | Literal has no `embed_jobs` / `build_pairs`. New nodes that write `failed_tasks` must extend it. |
| Job document | `models/collection_service.py:17-67` `JobPosting` | Indexable today: `uid`, `title`, `description_raw`, `tags`, `location`, `remote`, `source`, `company`, `posted_at`, `job_types`. **No seniority, no cleaned description, no embedding field.** (Resolved in Q3/Q4/Q10: flat baseline with stripped HTML; tags excluded; no ungrounded seniority field). |
| User profile | `models/users.py:153-174` `UserProfile` | Rich camelCase document (headline, skills, experience, `careerGoals.targetRoles`, `roleFitSignals`). Read-only from app code: `get_user_profiles` / `get_user_profile` (`repository/mongo_jobs_repository.py:258-266`). **No profile write API** (Resolved in Q6: embed at start of `build_pairs` with SHA-256 content-hash cache). |
| Job feed API | `api/routes/jobs.py:18-27` → `get_job_feed_items` | Request: `PaginatedDataRequest[JobFeedQuery]` (`models/generics.py:16-19`, `models/jobs_api.py:21-36`). Response items **require** `job` + `fit` (`JobFeedItem`). Resolved in Q2: stays the primary user feed endpoint for matching assessed jobs; gains keyword filtering (technology, employer, title). |
| Feed aggregation | `repository/mongo_jobs_repository.py:406-517` | `$match` assessments → `$group` latest per `job_uid` → `$lookup` jobs → `$lookup` applications → `$facet` count + `$skip/$limit`. Offset pages. Sort keys are ATS scores or `posted_at`. |
| Feed tests | `tests/integration/test_mongo_jobs_repo.py:51-69` | Assert page size and skipped exclusion against a seeded Mongo fixture. Any API change has to keep or replace this contract. |
| Health | `api/routes/health.py:21-37` `readyz` | Mongo ping only. OpenSearch must join this check once the API depends on it. Tests in `tests/unit/test_health.py` hard-code `checks: {mongodb: ...}`. |
| App lifespan | `main.py:31-52` | Mongo + Auth0 + `MongoJobsRepository` + S3. Search client belongs here (and in `api/deps.py`) if the API queries OpenSearch. |
| Embedding / models | `agents/model_factory.py` | Chat models only (Grok, Luna, GPT-5-mini). No embedding client. `OPENAI_API_KEY` is already required. |
| Telemetry | `telemetry.py` | TracerProvider + FastAPI/PyMongo/httpx/aiohttp instrumentation. **No metrics.** Epic 3 owns Prometheus; this epic should not wait on it. |
| Agent benchmarks | `benchmarks/screening/`, `benchmarks/fit_assessment/` | Frozen `dataset/<DDMMYYYY>/`, standalone runners (`scripts/run_*_benchmark.py`), markdown+JSON reports, **exit 0 even if metrics are poor**. CI (`.github/workflows/ci.yml`) runs `tests/unit` and `tests/integration/test_mongo_jobs_repo.py` against a Mongo service container — **no OpenSearch service**. |
| Ranking notes | `docs/candidate-job-ranking.md` | Prefers instruction-prefix models, BM25 on `tags` for stack, vector on role/experience, RRF fusion, and **a flat `description_raw` baseline before field-decomposed matching**. Conflicts with the epic's "just use `text-embedding-3-small`" on the model axis; agrees on RRF and two-stage retrieve-then-LLM. |
| Frontend (local clone, gitignored) | `react-app/src/pages/jobs/{JobsPage,JobFilters,JobList}.tsx`, `react-app/src/requests/jobs.ts`, `react-app/src/types/jobs.ts` | Assessed-feed UI, not keyword search. Default unapplied query: `min_cv_ats_match_score: 80`, `sort_by: posted_at`, `applied: false`. Filters: remote, location, sources, tags, score floors, deal-breakers, skipped — **no `q`**. `SearchOutlined` is “Apply filters”. Applied tab bulk-fetches up to 50×100 pages then client-filters by posted window. `JobFeedItem.fit` is required. Maps `exclude_skipped` → backend `skipped`. |
| Prior pipeline design | `docs/planning/langgraph-pipeline.md` decision 4 | Explicitly chose Cartesian `usernames × unique_jobs`. Reversed in Q1/Q5: replaced by retrieval-gated top-$K$ pairing filtered to the cycle batch, with Cartesian pairing retained as a config toggle (`PIPELINE_PAIR_MODE="cartesian"`). |

---

## Design

### Data model

**Mongo stays source of truth for raw collections.** `jobs` stores posting documents, `user_profiles` stores user profiles, and `assessments` stores evaluation records. `upsert_jobs` (`repository/mongo_jobs_repository.py:273-285`) `$set`s the full `JobPosting` dump on every persist — do not stash embeddings on the Mongo job document unless the upsert is changed to a partial `$set`, or they will be wiped.

**Two-index OpenSearch architecture (Q2, Q13):**

OpenSearch holds two dedicated indices:
1. `jobs` index (`OPENSEARCH_INDEX_NAME`): global corpus of unique job postings for pipeline retrieval gating, offline evaluation benchmarks, and future RAG.
2. `assessments` index (`OPENSEARCH_ASSESSMENTS_INDEX_NAME`): denormalized assessed-job records scoped to candidates, powering the user-facing job feed (`POST /jobs/search`) and replacing MongoDB `$lookup` aggregations.

#### 1. OpenSearch `jobs` index (Corpus)

Document id = `JobPosting.uid`. Mapping specifications (decided in Q3 and Q4):

| Field | Type | Role & Analyzer |
| --- | --- | --- |
| `uid` | `keyword` | Document identifier |
| `title` | `text` | BM25 (standard / english analyzer) |
| `description` | `text` | BM25 over HTML-stripped `description_raw` |
| `embedding` | `knn_vector` | 1536 dimensions (`text-embedding-3-small`, Q4), HNSW, cosine similarity |
| `source`, `company`, `location`, `url`, `job_types` | `keyword` | Filter and exact-match |
| `remote` | `boolean` | Filter |
| `posted_at` | `date` | Range filter / sort |

*Note on `tags`:* As decided in Q3, `tags` are **excluded** from search indexing and query analyzers altogether due to lack of standardization and reliability across scrapers.

#### 2. OpenSearch `assessments` index (User Feed)

Document id = `{username}_{job_uid}`. Self-contained denormalized assessment schema:

| Field | Type | Role |
| --- | --- | --- |
| `username` | `keyword` | Partitioning / filtering by authenticated user |
| `job_uid` | `keyword` | Job identifier |
| `cv_ats_match_score` | `float` | Filter range (e.g. $\ge 80$) and default sort |
| `profile_ats_match_score` | `float` | Secondary score filter / sort |
| `deal_breakers` | `keyword` | Array of deal-breaker strings; filter for empty |
| `summary` | `text` | Assessment summary |
| `status` | `object` | Nested status: `applied` (bool), `skipped` (bool), `stage` (keyword), `active` (bool), `cover_letter_key` (keyword) |
| `job` | `object` | Nested posting snapshot: `uid`, `title`, `company`, `location`, `remote`, `posted_at`, `description`, `source`, `url`, `job_types` |

BM25 analyzers are configured on nested `job.title`, `job.company`, and `job.description` to power the `q` parameter in `POST /jobs/search`.

#### MongoDB denormalization & synchronization

- **Denormalized Mongo `assessments`:** Mongo `assessments` documents also store nested `job` (snapshot of `JobPosting`) and `status` (`JobApplicationStatus`). Writes in `MongoJobsRepository.store_assessment` write the denormalized document to Mongo and index it into OpenSearch `assessments`.
- **Status synchronization:** When `PATCH /jobs/{job_uid}/status` is called, `update_job_application_status` updates MongoDB `job_applications`, updates the nested `status` in MongoDB `assessments`, and issues a partial update to OpenSearch `assessments` (`doc={"status": ...}`).
- **Migration & backfill:** `scripts/migrate_denormalized_assessments.py` reads existing historical Mongo `assessments`, joins `jobs` and `job_applications`, updates Mongo `assessments`, and bulk-indexes into OpenSearch `assessments`.

**User profile embeddings (Q6):** Dynamically generated at the start of `build_pairs` using `text-embedding-3-small` over a flattened profile string (headline, summary, skills, experience). To avoid unnecessary OpenAI API calls for unchanged profiles, an in-memory/process-level cache keyed by the SHA-256 hash of the profile string caches the vector. If the profile content hash has not changed since the last cycle, the cached vector is reused. This eliminates the need for a separate profile write API or dedicated `profiles` index in v1.

### Search service

Nothing named `SearchService` exists. Add a dedicated module (`search/` next to `repository/`, not inside `MongoJobsRepository`) so pipeline and API share one client.

The service manages both indices:

```python
class SearchService:
    async def ping(self) -> bool: ...
    async def ensure_indices(self) -> None: ...

    # --- Corpus jobs index (pipeline gating, benchmarks, RAG) ---
    async def bulk_index_jobs(self, docs: list[IndexedJob]) -> None: ...
    async def search_jobs(
        self,
        *,
        query_text: str | None,
        query_vector: list[float] | None,
        filters: SearchFilters,
        mode: Literal["bm25", "knn", "hybrid"],
        size: int,
    ) -> SearchHits: ...

    # --- Assessments index (candidate feed UI) ---
    async def index_assessment(self, doc: DenormalizedAssessment) -> None: ...
    async def update_assessment_status(
        self, username: str, job_uid: str, status: JobApplicationStatus
    ) -> None: ...
    async def search_user_feed(
        self,
        *,
        username: str,
        query: JobFeedQuery,
        page: int,
        page_size: int,
    ) -> PaginatedDataResponse[JobFeedItem]: ...
```

The three corpus search `mode`s (`bm25`, `knn`, `hybrid`) are required for the benchmark runner to compare retrieval strategies against the same index and gold set. `search_user_feed` executes native OpenSearch queries combining structured filters (username, status flags, score floors) with optional BM25 multi-match for `q`, returning `JobFeedItem`s with sub-50ms latency.

**Fusion (Q11):** Application-level RRF in Python is the source of truth for v1 ($RRF\_Score(d) = \sum_{m \in \{bm25, knn\}} \frac{1}{60 + rank_m(d)}$). For hybrid retrieval in `SearchService.search_jobs`, the service executes BM25 and k-NN vector queries in parallel (or via `_msearch`) and fuses their ranked lists in memory. This eliminates dependencies on cluster-side `neural-search` plugins or fragile search pipeline configurations across Docker Compose and CI containers, while sharing identical fusion logic directly with the offline benchmark harness. Optional cluster-native search pipelines can be added as a future optimization without affecting interface semantics.

**k-NN:** the official 2.19 image includes `opensearch-knn`. Compose already disables security.

### Embedding ingestion

**Job embeddings.** New batch node `embed_jobs` after `persist_jobs`:

1. Take `state["unique_jobs"]` (already persisted to Mongo).
2. Build embedding input text (`title + clean description`, HTML stripped, per Q3).
3. Batch-call the embedding API (`text-embedding-3-small` per Q4).
4. `SearchService.bulk_index_jobs`.
5. On failure (Q7): hard-fail the cycle immediately. Record a `failed_tasks` row (`node="embed_jobs"`) and re-raise/abort the pipeline. Do not proceed to `build_pairs` on a partial or un-indexed batch.

`FailedTask.NodeName` must include `"embed_jobs"` and `"build_pairs"`. `PipelineDeps` grows an embedding client + `SearchService`.

**Backfill.** `scripts/backfill_job_embeddings.py` (name from the epic): read Mongo `jobs`, embed, upsert OpenSearch. Needed before the API or pipeline can query historical postings. Idempotent on `uid`.

**Graph edge order with pair map re-enabled (decided in Q1):**

```text
persist_jobs → embed_jobs → build_pairs → fanout(pair_pipeline | finalize)
```

Today the last three are commented out (`orchestration/graph.py:49-67`). Q1 decides that this epic re-enables them together with top-$K$ gating in `build_pairs`.

### Retrieval-gated `build_pairs`

Current node (`orchestration/nodes/batch.py:136-150`):

```python
profiles = await repository.get_user_profiles()
pairs = build_pair_list([p.username for p in profiles], unique_jobs)
```

Replacement implementation (decided in Q5, Q6):

1. **Profile embeddings (Q6):** For each profile, compute or load cached embedding using SHA-256 content hash over profile text.
2. **Toggle check:** Check `config.PIPELINE_PAIR_MODE`. If `"cartesian"`, delegate directly to `build_pair_list` (explicit toggle for cost/quality evaluation).
3. **Candidate set restriction (Q5):** For `mode="topk"`, execute hybrid search in OpenSearch **filtered strictly to this cycle's `unique_jobs` UIDs** (`terms: {"uid": [j["uid"] for j in unique_jobs]}`). This guarantees candidates are evaluated against the newly scraped jobs and prevents older historical jobs from starving the new batch.
4. **Top-$K$ retrieval (Q5):** Size = `config.PIPELINE_RETRIEVAL_K` (default 20).
5. **Hydration:** Hydrate full `JobPosting` dicts directly from `unique_jobs` (already present in LangGraph state — zero Mongo round-trips required).
6. **Failure policy (Q5):** If OpenSearch is down or errors during retrieval, record `failed_tasks` (`node="build_pairs"`) and **fail the cycle** (re-raise). No silent fallback to Cartesian pairing, preventing accidental LLM spend spikes.
7. **Emit pairs:** Emit the same `{username, job_uid, job}` list that downstream `fanout` consumes.

Downstream pair subgraph does not change: screening still runs per pair, still idempotent.

### HTTP search API

Decided in Q2 and Q13: `POST /jobs/search` is migrated to query the OpenSearch `assessments` index directly, preserving the personalized assessed-job feed contract (`PaginatedDataResponse[JobFeedItem]`, requiring `job`, `fit`, and optional `status`).

- **Single-pass OpenSearch execution:** Eliminates the MongoDB `$lookup` aggregation bottleneck. OpenSearch natively executes the combination of structured filters (username, ATS score thresholds, deal-breakers, application status) and optional full-text BM25 search on `q`.
- **Search space:** Restricted to jobs deemed fitting (assessed for the current user).
- **Keyword search:** `JobFeedQuery` (`models/jobs_api.py`) gains an optional text parameter (`q: str | None = None`) allowing users to look up a specific technology, employer, title, or keywords within their assessed positions.
- **Corpus search:** Search across the entire unassessed job collection is strictly internal — used by the pipeline's `build_pairs` node as the initial retrieval gate, by the benchmark harness, and later by Epic 3's RAG assistant. No public raw job-board endpoint is introduced in this epic.
- **Pagination:** Offset pagination (`page` / `page_size`, `models/generics.py:8-19`) is retained on `POST /jobs/search` to avoid breaking existing UI clients and the applied-tab pagination loop.
- **Filters:** All existing assessment filters (`min_cv_ats_match_score`, `exclude_deal_breakers`, `application_stage`, `applied`, `active_only`, `skipped`) and job filters (`remote`, `sources`, `location`) remain intact and are mapped directly to OpenSearch query clauses.
- **Latency target:** $< 50\text{ms}$ (local single-node) for both internal top-$K$ corpus search and user feed queries. MongoDB fallback can be retained during transition as an operational safety net.

### Retrieval evaluation harness

Follow the existing benchmark layout, not invent a pytest-only world and then discover CI cannot talk to OpenSearch.

```text
benchmarks/retrieval/
  dataset/<DDMMYYYY>/   # queries, corpus subset or UID list, graded qrels
  metrics.py            # Recall@K, nDCG@K, MRR — unit-tested, no IO
  reports/              # gitignored generated output
scripts/run_retrieval_benchmark.py
```

Runner compares three `SearchService` modes on the same gold set and writes markdown + JSON, same as screening/fit.

- **Gold set labeling (Q8):** Evaluates ~100 candidate–job query-document pairs derived from historical assessments for benchmark users. Relevance scale: Grade 3 (ATS score $\ge 80$), Grade 2 (60–79), Grade 1 (<60, screened through), Grade 0 (screened out / irrelevant). Dataset is frozen under `benchmarks/retrieval/dataset/<DDMMYYYY>/` with precomputed vectors.
- **CI evaluation smoke (Q9):** A dedicated OpenSearch service container is added to `.github/workflows/ci.yml`. CI runs a deterministic smoke test over a tiny frozen split (~10 queries with precomputed vectors in git, zero network calls to OpenAI) via `pytest benchmarks/retrieval/test_retrieval_smoke.py`. CI fails if search fails or nDCG@10 drops below a committed baseline JSON.
- **Full benchmark runner:** `scripts/run_retrieval_benchmark.py` runs the comprehensive 100-query benchmark on-demand or nightly, generating comparative reports across BM25, k-NN, and hybrid modes.

Epic acceptance ("hybrid nDCG@10 ≥ 15% over single-modality") is a **goal**, not a fact. Flat baseline (Q3) may not hit it; do not bake the 15% into CI until a full run exists.

### Observability

Epic 3 owns Prometheus/Grafana. This epic adds structured logs/spans only: extend `pipeline_build_pairs` with `n_pairs`, `n_jobs`, `n_users`, `k`, `mode`, and a derived `llm_calls_saved` ≈ `n_users * n_jobs - n_pairs`. Search path: span duration per query. No cache exists, so “cache hit ratio” is not a v1 metric.

`readyz` gains an OpenSearch ping.

### Frontend

Decided in Q2 and Q12: The primary UI continues to render assessed matching positions. Changes to the client web application (`react-app/`) will not be implemented directly within this backend repository. Instead, this repo delivers the backend API contract (`POST /jobs/search` accepting optional `q: str | None`), OpenAPI schema updates, and contract integration tests.

A dedicated implementation plan (`docs/planning/client-search-ui-implementation-plan.md`) will be produced for the UI side. That plan will specify:
1. Adding a text/keyword input for `q` to `JobFilters.tsx` (searching by technology, employer, or title within matching assessed positions).
2. Updating `JobFeedQuery` in `react-app/src/types/jobs.ts` and `react-app/src/requests/jobs.ts` to forward `q`.
3. Verifying that the applied tab bulk fetch loop (`fetchAllJobFeedItems`) continues functioning cleanly.
4. Testing the user experience in the respective UI repository/project environment.

---

## Open questions

None. All 13 questions have been deliberated and resolved (see Decision log below).

---

## Decision log

### Q1 — Re-enable pair subgraph with retrieval gating

**Decided:** 2026-09-04
Re-enable the pair subgraph (`build_pairs` → `fanout(pair_pipeline | finalize)`) in `orchestration/graph.py` as part of this epic, coupled directly with top-$K$ retrieval gating in `build_pairs`.

**Rejected:**
- Leaving the pair subgraph commented out — defeats the epic's core outcome (cannot demonstrate an 80–90% reduction in pair screening LLM calls if pairs never execute).
- Re-enabling Cartesian pairing first without gating — immediately triggers high LLM spend on production cycles, which was the reason it was disabled in commit `11e9df1`.

**Consequence:** Phase 3 must re-connect the graph edges (`persist_jobs` → `embed_jobs` → `build_pairs` → `fanout(pair_pipeline | finalize)`) simultaneously with the gated `build_pairs` implementation. Downstream pair nodes (`screen`, `assess`, `cover_letter`) stay unchanged and idempotent.

### Q2 — Retain assessed job feed as primary UI; keyword search filters within assessed matches; full corpus search is internal

**Decided:** 2026-09-04
Retain `POST /jobs/search` as the user-facing assessed job feed (returning `JobFeedItem` with `fit` and `status` for matching positions). Text/keyword search in the UI is an additional filter enabling users to look for a specific technology, employer, title, etc., strictly restricted to jobs that have been deemed fitting (assessed for that user). Full-corpus search across the entire set of collected jobs is reserved for internal use: primarily as the initial retrieval gate in the ingestion/processing pipeline (`build_pairs`), the benchmark evaluation suite, and future RAG retrieval (Epic 3).

**Rejected:**
- Option 2 (OpenSearch retrieves all job UIDs first and Mongo hydrates optional `fit`): breaks the UI contract that every feed card displays an assessed match with ATS scores; requires handling unassessed items or oversized fetches.
- Option 3 (Replace the feed with corpus-wide search): fundamentally alters the product experience from a personalized high-fit job inbox to an unranked raw job board.

**Consequence:**
- `JobFeedQuery` (`models/jobs_api.py`) gains an optional text/keyword search field `q: str | None = None` to filter within assessed matching positions.
- Offset pagination (`page`, `page_size`) on `POST /jobs/search` is preserved, maintaining compatibility with the React UI and the applied-tab pagination loop.
- `SearchService` serves internal retrieval needs (`build_pairs` top-$K$ gating, offline benchmark harness, and future RAG) via the `jobs` index, and powers candidate feed queries via the `assessments` index.
- Execution architecture resolved in Q13 (below).

### Q3 — Flat baseline for v1; tags excluded from search indexing and query analyzers

**Decided:** 2026-09-06
Adopt Approach A (Flat baseline) for v1 retrieval:
1. Dense vector: Exactly one 1536-dimensional embedding vector per job, computed over `title + clean description` (HTML stripped from `description_raw`). Profile embedding computed over flattened profile text (headline, summary, skills, experience).
2. Lexical search: Standard BM25 over `title` and `description` (HTML stripped from `description_raw`).
3. Tags excluded from search: `tags` are excluded from OpenSearch search indexing and query analyzers altogether. Tags collected from job board scrapers are unstandardized, noisy, and cause false-positive matches; existing DB records retain tags for display, but search does not index or query them.

**Rejected:**
- Field-decomposed / multi-vector matching (e.g. separate requirements vector, title vector, stack vector): requires ungrounded NLP enrichment, introduces complex weighting hyperparameters, and premature optimization before establishing a quantitative baseline.
- Indexing and matching on scraper `tags`: degrades retrieval precision due to inconsistent scraper tagging across sources.

**Consequence:** The OpenSearch `jobs` index mapping has a single `knn_vector` field (`embedding`). Ingestion generates one embedding string per posting. Lexical queries target `title` and `description` only. Future multi-vector experiments will be benchmarked against this flat baseline.

### Q4 — Embedding model: `text-embedding-3-small` (1536-d)

**Decided:** 2026-09-06
Adopt OpenAI `text-embedding-3-small` (1536 dimensions) for all job and user profile embeddings in v1.

**Rejected:**
- Self-hosted / open-source instruction models (e.g. E5 / BGE): introduces heavy operational complexity, requires GPU/inference hosting infra, and increases cold-start/dependency overhead.
- `text-embedding-3-large`: ~5× higher cost with negligible retrieval delta for the coarse-grained top-$K$ initial retrieval gate.

**Consequence:** Vector dimension in OpenSearch mappings is fixed to 1536. `OPENAI_API_KEY` is already present in `config.py`. Backfill and pipeline embedding costs remain negligible (~$0.02 / 1M tokens).

### Q13 — Two-index architecture with denormalized assessments for candidate feed search

**Decided:** 2026-09-06
Implement a two-index OpenSearch architecture with denormalized assessment documents to power `POST /jobs/search`:
1. `jobs` index (`OPENSEARCH_INDEX_NAME`): Stores raw corpus postings with 1536-d vectors for pipeline `build_pairs` gating, benchmarks, and future RAG.
2. `assessments` index (`OPENSEARCH_ASSESSMENTS_INDEX_NAME`): Stores denormalized assessment documents scoped to `{username}_{job_uid}`, containing ATS match scores, deal breakers, summary, nested `job` snapshot, and nested `status`.

`POST /jobs/search` queries the `assessments` index directly in OpenSearch, executing structured filters (username, ATS thresholds, deal breakers, status) and optional BM25 keyword matching (`q`) across `job.title`, `job.company`, and `job.description` in a single sub-50ms query.

**Rejected:**
- MongoDB `$lookup` aggregation with OpenSearch UID pre-filtering: retains the complex join and facet pipeline in Mongo, adding network round-trip overhead.
- Pure MongoDB `$match` regex: poor performance, lacks BM25 scoring and proper linguistic stemming.

**Consequence:**
- MongoDB `$lookup` aggregation in `repository/mongo_jobs_repository.py:351-517` is bypassed for candidate feeds.
- MongoDB `assessments` collection is also updated to store nested `job` and `status` snapshots for single-document persistence.
- `update_job_application_status` synchronizes status updates to OpenSearch `assessments` index (`doc={"status": ...}`).
- A migration script `scripts/migrate_denormalized_assessments.py` backfills and indexes existing historical assessments.

### Q11 — Application-level Reciprocal Rank Fusion (RRF) for v1

**Decided:** 2026-09-06
Adopt application-level Reciprocal Rank Fusion (RRF) in Python as the primary fusion mechanism for v1 hybrid search (`SearchService.search_jobs(mode="hybrid")`):
$$RRF\_Score(d) = \sum_{m \in \{bm25, knn\}} \frac{1}{60 + rank_m(d)}$$

The service executes BM25 and k-NN vector queries (via `_msearch` or parallel async requests) and fuses the ranked lists in memory.

**Rejected:**
- Native OpenSearch cluster search pipeline (`score-ranker-processor`) as primary for v1: introduces cluster plugin dependencies (`opensearch-neural-search`), configuration fragility across local Docker Compose and CI service containers, and causes logic duplication between runtime search and offline evaluation harness.

**Consequence:**
- `SearchService` executes dual queries against OpenSearch and applies RRF in Python.
- Exact same fusion code (`search/rrf.py`) is shared directly with the retrieval benchmark harness (`benchmarks/retrieval/metrics.py`).
- Phase 1 does not need to configure cluster-side search pipelines or plugin dependencies. Cluster search pipelines may be added as an optional performance optimization in a future iteration.

### Q5 — Candidate set restricted to cycle batch, $K=20$, explicit Cartesian toggle, hard-fail on outage

**Decided:** 2026-09-06
1. **Candidate set:** For `mode="topk"`, hybrid retrieval in `build_pairs` is strictly filtered to this cycle's `unique_jobs` UIDs (`terms: {"uid": [j["uid"] for j in unique_jobs]}`). This guarantees that candidates are evaluated against newly collected postings and prevents historical neighbours from starving the new batch.
2. **$K=20$:** Configurable via `config.PIPELINE_RETRIEVAL_K` (default 20).
3. **Pair mode toggle:** `config.PIPELINE_PAIR_MODE="topk" | "cartesian"` (default `"topk"`). Cartesian mode is an explicit config escape hatch for the cost/quality A/B comparison requested by the epic.
4. **Outage policy:** If OpenSearch is unreachable or errors during `build_pairs`, log `FailedTask(node="build_pairs")` and **fail the cycle** (re-raise). No silent fallback to Cartesian pairing, preventing unexpected LLM cost spikes.

**Rejected:**
- Searching full corpus for new batch pairing: risks retrieving already-screened historical postings, starving today's batch.
- Automatic/silent fallback to Cartesian: masks OpenSearch outages and triggers massive LLM costs.

**Consequence:**
- Ingestion cycles scale at $O(\text{users} \times K)$ (e.g. 50 users × 20 = 1,000 pairs max, vs 25,000 Cartesian pairs).
- Pair nodes receive `{username, job_uid, job}` with jobs hydrated directly from graph state.

### Q6 — User profile embeddings computed at start of `build_pairs` with content-hash cache

**Decided:** 2026-09-06
Compute user profile embeddings dynamically at the start of `build_pairs` using `text-embedding-3-small` over flattened profile text (headline, summary, skills, experience). Use an in-memory/process-level cache keyed by the SHA-256 hash of the profile string:
- If a profile's text has not changed, reuse the cached vector (0 OpenAI API calls).
- If a user is new or their profile text changed, generate and cache the new embedding.

**Rejected:**
- Storing profile vectors in a separate OpenSearch `profiles` index or inventing a profile write API in this epic: over-engineers profile storage when no profile update API endpoint exists in the backend yet.
- Re-embedding every user on every cycle without caching: wastes API cost and adds cycle latency.

**Consequence:**
- Profile embeddings are always fresh without needing complex DB migrations or invalidation hooks.
- Operational cost for 50 users is negligible (re-embed only occurs when profiles change).

### Q7 — `embed_jobs` hard-fail policy

**Decided:** 2026-09-06
Adopt a hard-fail policy for `embed_jobs`:
If the OpenAI embedding API or OpenSearch bulk indexing fails, record a `failed_tasks` row (`node="embed_jobs"`) and **fail the cycle** (re-raise/abort the pipeline graph).

**Rejected:**
- Best-effort / partial batch indexing: allows OpenSearch to lag Mongo, causing new jobs to be silently skipped during `build_pairs`.
- Proceeding to `build_pairs` on partial indexing: produces incomplete pairs and creates subtle data discrepancies.

**Consequence:**
- Preserves data consistency: all jobs in a cycle are indexed in OpenSearch before retrieval gating runs.
- `FailedTask.NodeName` is extended to include `"embed_jobs"` and `"build_pairs"`.
- Operators can retry transient failures or run `scripts/backfill_job_embeddings.py` to reconcile.

### Q8 — Frozen retrieval gold set derived from historical ATS assessments

**Decided:** 2026-09-06
Adopt an automated ATS-band mapping from historical assessments to construct the ~100 candidate–job query-document gold set for v1 retrieval benchmarking:
- **Grade 3 (Highly relevant):** ATS score $\ge 80$ (band `good`).
- **Grade 2 (Relevant):** ATS score 60–79 (band `moderate`).
- **Grade 1 (Marginally relevant):** ATS score < 60, but passed screening and was deemed worth assessing.
- **Grade 0 (Not relevant):** Postings dropped during initial screening or never retrieved for the user.

The dataset is frozen under `benchmarks/retrieval/dataset/<DDMMYYYY>/` with precomputed embedding vectors.

**Rejected:**
- Manual human labeling for v1: costly, slow, and delays initial retrieval evaluation. Human re-labeling can be introduced in a future revision of the dataset layout.

**Consequence:**
- Enables immediate, deterministic benchmarking of Recall@K, nDCG@K, and MRR.
- The evaluation reports will explicitly document that ground-truth labels are proxy-derived from historical LLM assessments.

### Q9 — Two-tier CI evaluation: deterministic smoke gate on PRs, comprehensive benchmark on demand

**Decided:** 2026-09-06
Adopt a two-tier evaluation strategy:
1. **CI Smoke Test:** Add an OpenSearch service container to `.github/workflows/ci.yml`. CI runs a deterministic smoke test over a tiny frozen split (~10 queries with precomputed vectors committed to git) via `pytest benchmarks/retrieval/test_retrieval_smoke.py`. Zero network calls to OpenAI. CI fails if retrieval errors or if nDCG drops below a committed baseline JSON.
2. **Comprehensive Benchmark:** `scripts/run_retrieval_benchmark.py` runs the full ~100-query benchmark on-demand or nightly, generating detailed markdown/JSON comparison reports across BM25, k-NN, and hybrid modes.

**Rejected:**
- Running the full 100-query benchmark with live OpenAI embedding API calls on every PR: costly, slow, and prone to external API flakiness.
- Report-only / non-failing smoke test in CI: fails to prevent ranking regressions from slipping into `main`.

**Consequence:**
- `.github/workflows/ci.yml` is updated with an OpenSearch 2.19 service container.
- PRs are protected against ranking regressions with zero API cost and fast execution.
- Baseline thresholds in CI will be committed only after the first full baseline run establishes ground-truth numbers.

### Q10 — Omit seniority structured facet for v1; support seniority terms via keyword search `q`

**Decided:** 2026-09-06
Omit `seniority` as an explicit structured facet/filter field in v1. Structured facets in v1 are restricted to verified schema fields (`remote`, `source`, `location`, `posted_at`). Seniority-related intent (e.g. searching for `"senior"`, `"lead"`, `"staff"`, `"junior"`) is handled naturally by full-text BM25 search over titles and descriptions via the new `q` parameter on `POST /jobs/search`.

**Rejected:**
- Title regex heuristics (`Senior`, `Staff`, etc.): noisy, high error rates, unmaintainable list of edge cases.
- Building an NLP description enrichment / seniority extraction agent in v1: premature complexity; `docs/candidate-job-ranking.md` designates enrichment as a future quality lever.

**Consequence:**
- OpenSearch mappings and API query models do not include an ungrounded `seniority` field.
- When an NLP description enrichment agent is added in a future epic, seniority can be extracted, backfilled, and introduced as a structured facet.

### Q12 — Client UI changes planned separately; this repository delivers backend API & contract handoff

**Decided:** 2026-09-06
Changes in this repository will **not** modify client application code (`react-app/`) directly. Instead:
1. This repository implements and verifies the backend API surface: `POST /jobs/search` accepting optional `q: str | None`, schema updates in `models/jobs_api.py`, OpenAPI contract tests, and OpenSearch query execution.
2. A separate standalone implementation plan (`docs/planning/client-search-ui-implementation-plan.md`) will be produced for the UI side, specifying the UI changes needed in the client application's own repository and environment.

**Rejected:**
- Directly modifying `react-app/` in this repository / CI workflow: `react-app/` is gitignored and excluded from backend CI/linting; blending frontend code changes here violates repo boundary conventions and risks unverified frontend deployments.

**Consequence:**
- Scope in this repo is cleanly bounded to backend services, pipeline, OpenSearch, API contracts, and retrieval benchmarks.
- Phase 6 delivers the UI implementation plan artifact (`docs/planning/client-search-ui-implementation-plan.md`) and verified OpenAPI contract documentation for seamless client integration.

---

## Deliberation summary

All 13 open questions (Q1–Q13) have been deliberated and resolved. The implementation plan is **Ready for implementation**. See the Decision log above for the rationale, consequences, and rejected alternatives for every decision.

---

## Implementation phases

The feature is organized into 6 concrete, independently reviewable phases:

### Phase 1 — OpenSearch client, two-index schemas, `SearchService`

**Depends on:** Q3 (resolved), Q4 (resolved), Q11 (resolved), Q13 (resolved)
**Reviewable when:** compose OpenSearch accepts mappings for both `jobs` and `assessments` indices; BM25, k-NN, and hybrid queries via application-level RRF return hits in a unit/integration test against a CI/service container; `readyz` pings OpenSearch; `opensearch-py` is a locked dependency.
**Touches:** `pyproject.toml` / `uv.lock`, `config.py`, new `search/` package, `main.py` lifespan, `api/deps.py`, `api/routes/health.py`, `.github/workflows/ci.yml` (OpenSearch service)

-

### Phase 2 — Embeddings + `embed_jobs` + corpus backfill

**Depends on:** Phase 1, Q6 (resolved), Q7 (resolved)
**Reviewable when:** a cycle's `unique_jobs` land in OpenSearch `jobs` index with 1536-d vectors; `scripts/backfill_job_embeddings.py` indexes historical Mongo `jobs`; failure handling matches Q7.
**Touches:** `orchestration/nodes/batch.py`, `orchestration/graph.py`, `orchestration/deps.py`, `models/failed_tasks.py`, `scripts/backfill_job_embeddings.py`

-

### Phase 3 — Retrieval-gated `build_pairs` (+ re-enable pair map & denormalized assessment storage)

**Depends on:** Phase 2, Q1 (resolved), Q5 (resolved)
**Reviewable when:** with $N$ jobs and $U$ users, `n_pairs <= U * K`; pair subgraph runs on that list; graph edges re-connected; completed assessments write denormalized documents to Mongo and index into OpenSearch `assessments`.
**Touches:** `orchestration/nodes/batch.py`, `orchestration/graph.py`, `orchestration/state.py`, `orchestration/nodes/assess.py`, `repository/mongo_jobs_repository.py`, `config.py`, `tests/unit/test_pipeline_routing.py`

-

### Phase 4 — Assessed-feed migration & status sync

**Depends on:** Phase 1, Phase 3, Q2 (resolved), Q13 (resolved), Q10 (resolved)
**Reviewable when:** `POST /jobs/search` queries OpenSearch `assessments` directly with sub-50ms latency; `JobFeedQuery` accepts optional `q` and filters within assessed positions; status updates via `PATCH /jobs/{job_uid}/status` synchronize to OpenSearch; `scripts/migrate_denormalized_assessments.py` successfully migrates existing historical assessments.
**Touches:** `api/routes/jobs.py`, `models/jobs_api.py`, `models/assessments.py`, `repository/mongo_jobs_repository.py`, `search/search_service.py`, `scripts/migrate_denormalized_assessments.py`

-

### Phase 5 — Retrieval harness + CI smoke

**Depends on:** Phase 1 (can overlap Phase 2–4), Q8 (resolved), Q9 (resolved)
**Reviewable when:** `metrics.py` unit tests exist; smoke test runs against CI OpenSearch service and fails on regression; full runner produces BM25 vs k-NN vs hybrid report.
**Touches:** `benchmarks/retrieval/`, `scripts/run_retrieval_benchmark.py`, `.github/workflows/ci.yml`

-

### Phase 6 — UI implementation plan & contract handoff

**Depends on:** Phase 4, Q12 (resolved)
**Reviewable when:** `docs/planning/client-search-ui-implementation-plan.md` is authored and reviewed; OpenAPI schema export confirms `JobFeedQuery.q`; backend contract tests pass.
**Touches:** `docs/planning/client-search-ui-implementation-plan.md`, `tests/integration/test_jobs_api.py`

-
