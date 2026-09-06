# Retrieval Benchmark

Offline comparison of BM25, k-NN, and hybrid RRF against a frozen gold set.
Labels are ATS-band proxies (Q8): grade 3 if ATS ≥ 80, grade 2 if 60–79,
grade 1 if screened through below 60, grade 0 otherwise.

Planning doc: [`docs/planning/hybrid-search-retrieval-eval-implementation-plan.md`](../../docs/planning/hybrid-search-retrieval-eval-implementation-plan.md)

## Layout

```text
benchmarks/retrieval/
  dataset/
    06092026/                  # CI smoke set (10 queries, 20 docs, zero-cost CI)
    06092026_comprehensive/    # Comprehensive benchmark (100 queries, 387 real docs, 21k+ qrels)
  metrics.py                   # Recall@K, nDCG@K, MRR — unit-tested, pure functions
  dataset.py                   # Dataset loader and schema definitions
  test_retrieval_smoke.py      # CI smoke test against OpenSearch service container
  reports/                     # gitignored generated reports (.md and .json)
```

### Datasets

- **`06092026` (CI Smoke):** A tiny split (10 queries, 20 corpus docs) with deterministic 1536-d vectors for fast, zero-cost PR regression gates in CI (`pytest benchmarks/retrieval/test_retrieval_smoke.py`).
- **`06092026_comprehensive` (Comprehensive Benchmark):** A full evaluation dataset with 100 queries and 387 real job postings derived from historical ATS assessments and diverse search intents across Python, Full Stack, AI/RAG, Cloud/DevOps, Data Engineering, and Java/Go/C#. Precomputed with 1536-d `text-embedding-3-small` vectors.

## Generating / Exporting Datasets

Generate a fresh versioned dataset from MongoDB (or historical assessment entries when MongoDB is offline):

```bash
# Generate comprehensive dataset with precomputed OpenAI embeddings
uv run python scripts/generate_retrieval_benchmark_dataset.py --dataset-version 06092026_comprehensive

# Or using the registered entrypoint
uv run export-retrieval-benchmark-dataset --dataset-version 06092026_comprehensive

# Generate offline with deterministic vectors (no OpenAI API calls)
uv run python scripts/generate_retrieval_benchmark_dataset.py --dataset-version test_offline --deterministic-vectors
```

## Running Benchmarks

```bash
# Run comprehensive benchmark across BM25, k-NN, and hybrid RRF (needs OpenSearch)
uv run python scripts/run_retrieval_benchmark.py --dataset-version 06092026_comprehensive

# Or run against latest dataset version
uv run run-retrieval-benchmark

# CI smoke test (runs in GitHub Actions on PRs against OpenSearch container)
uv run pytest benchmarks/retrieval/test_retrieval_smoke.py
```
