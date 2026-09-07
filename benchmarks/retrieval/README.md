# Retrieval Gating Benchmark

Offline evaluation of the `search/` module's retrieval gating function (`build_pairs` in `orchestration/nodes/batch.py`).
The benchmark measures how effectively the search tier reduces the number of candidate jobs requiring expensive downstream LLM assessments while retaining as many fitting jobs as possible.

All 300 corpus jobs are queried against a single candidate query (formulated from the candidate's `cv.pdf` as `query_text` and `query_vector`).

## Evaluation Objective & Ground Truth

The dataset repurposes 300 stratified postings from the screening benchmark (`benchmarks/screening/dataset/05082026/`):
- **30 Good jobs:** Historical ATS score $\ge 70$, deemed top-tier candidate matches.
- **60 Moderate jobs:** Historical ATS score $50$–$69$, deemed viable fitting opportunities.
- **210 Low jobs:** Historical ATS score $< 50$, non-fitting roles that should be pruned.
- **Total Fitting:** 90 jobs (`worth_full_assessment = True`).

## Layout

```text
benchmarks/retrieval/
  dataset/
    05082026/                  # Frozen gating benchmark (300 jobs + candidate query + precomputed 1536-d embeddings)
      candidate.json           # UserProfile, query_text, and query_vector
      corpus.jsonl             # 300 jobs with clean text, 1536-d embeddings, and gold labels
      manifest.json            # Dataset metadata and stratification counts
      baseline.json            # Regression floor values for CI gating
  metrics.py                   # Gating metrics (fitting recall, good recall, reduction rate, LLM calls saved, nDCG, MRR)
  dataset.py                   # Dataset loader and schema definitions
  test_retrieval_smoke.py      # CI smoke test against OpenSearch service container
  reports/                     # gitignored generated reports (.md and .json)
```

## Metrics

For each ranking cutoff depth $K \in [20, 50, 90, 100, 150]$ across BM25, k-NN, and Hybrid RRF:
- **Good Recall@K:** Fraction of the 30 top-tier jobs captured in top-$K$.
- **Moderate Recall@K:** Fraction of the 60 viable moderate jobs captured in top-$K$.
- **Fitting Recall@K:** Fraction of all 90 fitting jobs captured in top-$K$.
- **Naive Recall@K:** Expected recall if a sample of $K$ postings was drawn uniformly at random without replacement from the corpus ($\frac{\min(K, N)}{N}$). Serves as the baseline benchmark to evaluate the lift added by retrieval over random sampling.
- **Reduction Rate:** Percentage of downstream LLM assessments avoided: $\frac{N - \min(K, N)}{N}$ (e.g. 93.3% at $K=20$).
- **LLM Calls Saved:** Total LLM assessments avoided per cycle (e.g. 280 at $K=20$).
- **nDCG@K:** Graded ranking quality (grades 3 for good, 2 for moderate, 0 for low).
- **MRR:** Mean Reciprocal Rank of the first fitting job.

## Generating Datasets

Generate or re-export the frozen gating dataset from the screening dataset:

```bash
# Extract candidate profile from cv.pdf and embed corpus via OpenAI text-embedding-3-small
uv run python scripts/generate_gating_benchmark_dataset.py --dataset-version 05082026

# Or using registered entrypoint
uv run generate-retrieval-benchmark-dataset --dataset-version 05082026

# Generate offline with deterministic unit vectors (zero API calls)
uv run python scripts/generate_gating_benchmark_dataset.py --dataset-version test_offline --deterministic-vectors
```

## Running Benchmarks

```bash
# Run candidate gating benchmark across BM25, k-NN, and Hybrid RRF (requires OpenSearch)
uv run python scripts/run_retrieval_benchmark.py --dataset-version 05082026

# Or run against latest dataset version
uv run run-retrieval-benchmark

# CI smoke test (runs in GitHub Actions on PRs against OpenSearch container)
uv run pytest benchmarks/retrieval/test_retrieval_smoke.py
```
