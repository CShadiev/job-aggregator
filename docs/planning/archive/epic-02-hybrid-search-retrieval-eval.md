# Epic 2: Hybrid Search & Retrieval Evaluation Harness

**Status:** Planned  
**Prerequisites:** Epic 1 (Local compose environment & CI pipeline)  
**Scope:** OpenSearch hybrid search tier, ingestion embeddings, retrieval-gated pipeline, offline retrieval benchmark suite, and search UI integration.  
**Demonstrable Outcome:** 80–90% reduction in pipeline LLM screening calls by replacing Cartesian fan-out with hybrid top-$K$ retrieval, backed by reproducible benchmark metrics (Recall@K, nDCG, MRR) proving search ranking quality.

---

## 1. Problem Statement & Motivation

1. **Unbounded LLM Cost Curve:** The pipeline currently pairs every new job with every registered candidate (`build_pairs` in `orchestration/nodes/batch.py`). With 500 jobs/day and 50 users, this triggers **25,000 LLM calls/day** ($O(\text{users} \times \text{jobs})$).
2. **Naive Search Endpoint:** `POST /jobs/search` relies on heavy MongoDB aggregations with `$lookup` and post-join sorting. It cannot perform semantic matching, keyword search, or faceted discovery.
3. **Unmeasured Retrieval Quality:** Without a gold-standard evaluation harness, search improvements are subjective. We need quantitative proof that hybrid search (BM25 + Dense Vectors + RRF) outperforms pure keyword or pure vector search.

---

## 2. Vertical Slice Deliverables

### A. Search Tier & Ingestion Embeddings
- **OpenSearch Index Schema:**
  - `jobs` index with BM25 text analyzers for `title`, `description`, and `tags` (with synonym support).
  - `knn_vector` field (e.g. 1536-dimensional using HNSW with cosine or dot product similarity).
- **Search Pipeline with Reciprocal Rank Fusion (RRF):**
  - Configure OpenSearch search pipeline with `score-ranker-processor` (RRF) / min-max score normalizer to fuse BM25 lexical and k-NN vector scores.
  - Implement application-level fallback ranker in `SearchService` to safeguard against local plugin discrepancies.
- **Embedding Ingestion Node in LangGraph:**
  - Add an `embed_jobs` node after `persist_jobs` that generates embeddings in batches using an efficient model API (`text-embedding-3-small`).
  - Add user profile embedding generation triggered on profile updates.
  - Backfill script (`scripts/backfill_job_embeddings.py`) to index historical postings into OpenSearch.

### B. Retrieval-Gated Pipeline
- **Smart `build_pairs` Node:**
  - Instead of computing Cartesian product $\text{users} \times \text{jobs}$, query OpenSearch for top-$K$ most relevant jobs for each user profile.
  - Configurable $K$ parameter (default e.g., $K=20$) with feature toggle for A/B cost and quality comparison.
  - Downstream screening and fit assessment agents now execute on $O(\text{users} \times K)$ pairs.

### C. Advanced Search API
- **Revamped `POST /jobs/search`:**
  - Migrate feed queries from Mongo aggregation to OpenSearch `SearchService`.
  - Support free-text keyword search, semantic similarity, and faceted filtering (location, seniority, tags, date posted).
  - Keyset/cursor-based pagination for high-performance scrolling.

### D. Retrieval Evaluation Benchmark Suite
- **Evaluation Harness (`benchmarks/retrieval/`):**
  - Curate a gold-standard test dataset of ~100 candidate–job pairs with multi-graded relevance labels (0 = irrelevant, 1 = partial, 2 = strong, 3 = perfect match).
  - Implement benchmark runner calculating:
    - **Recall@K** (proportion of relevant items retrieved in top $K$).
    - **nDCG@K** (Normalized Discounted Cumulative Gain accounting for rank positions).
    - **MRR** (Mean Reciprocal Rank).
  - Generate comparative markdown and JSON reports comparing:
    1. BM25 text search only
    2. Dense vector search only
    3. Hybrid search with RRF fusion

### E. Observability, CI & UI Integration
- **Metrics & Logging:**
  - Record OpenSearch query latency (p50, p95) and cache hit ratios.
  - Telemetry counters for pipeline runs: `jobs_collected`, `pairs_built`, `llm_calls_saved`.
- **CI Smoke Benchmark:**
  - Add a fast retrieval evaluation subset to CI to ensure no PR degrades search metrics below established thresholds.
- **Frontend Search UI:**
  - Connect React UI search bar and faceted filter chips to the new `POST /jobs/search` API.

---

## 3. Step-by-Step Execution Plan

| Step | Task | Deliverable |
| --- | --- | --- |
| **2.1** | OpenSearch client & index schema | `SearchService` class, index mappings, analyzers, and RRF pipeline. |
| **2.2** | Embedding pipeline node & backfill | `embed_jobs` node in LangGraph, batch embedding client, backfill script. |
| **2.3** | Retrieval-gated `build_pairs` | Top-$K$ retrieval in batch orchestration, saving ~80% pair fan-out. |
| **2.4** | Search API upgrade | Update `POST /jobs/search` with full-text + facets via OpenSearch. |
| **2.5** | Retrieval benchmark harness | `benchmarks/retrieval/` with gold dataset, Recall@K / nDCG runner, CI check. |
| **2.6** | UI search integration | React UI search input, facet filters, and score badges verified. |

---

## 4. Acceptance Criteria & Verification

- [ ] Pipeline execution on 100 jobs and 5 users creates $\le 5 \times K$ pairs instead of $500$ pairs ($O(\text{users} \times K)$ proven).
- [ ] `POST /jobs/search` executes full-text and faceted search against OpenSearch with response times $< 50\text{ms}$.
- [ ] Running `pytest benchmarks/retrieval/` produces a quantitative report proving Hybrid RRF outperforms single-modality baselines (e.g. nDCG@10 gain of $\ge 15\%$).
- [ ] CI pipeline runs retrieval benchmark smoke test on pull requests.
- [ ] React UI performs live keyword search and faceted filtering against the running backend.
