# Retrieval Gating Benchmark

Offline evaluation of the `search/` module's retrieval gating function (`build_pairs` in `orchestration/nodes/batch.py`).
The benchmark measures how effectively the search tier reduces the number of candidate jobs requiring expensive downstream LLM assessments while retaining as many fitting jobs as possible.

All 300 corpus jobs are queried against a single candidate query (formulated from the candidate's `cv.pdf` as `query_text` and `query_vector`).

The corpus, `candidate.json`, and `extracted_profile.json` are private.
`baseline.json` stays committed. Reports, including the hybrid ranked-uid list,
are public. A stranger can recompute recall from that list plus the screening
`.results.jsonl`; they cannot re-index the corpus.

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
    05082026/                  # Private corpus. Only baseline.json is committed.
      baseline.json            # Regression floor. CI checks the ranked-uid list against it.
  metrics.py                   # Gating metrics (fitting recall, good recall, reduction rate, LLM calls saved, nDCG, MRR)
  dataset.py                   # Dataset loader and schema definitions
  composition.py               # Replay of retrieval + stored screening predictions
  test_retrieval_smoke.py      # Public ranked-uid assertion, plus a maintainer OpenSearch re-index
  reports/                     # Public: markdown, JSON, ranked uids, composed-gate report
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

The generated corpus stays untracked. Only `baseline.json` is committed from a dataset directory.

## Running Benchmarks

The headline table is hybrid / BM25 / k-NN at K=150, the cutoff
`PIPELINE_RETRIEVAL_RATIO=0.5` selects on this 300-job corpus. Other cutoffs
stay in the sweep.

```bash
# Run candidate gating benchmark across BM25, k-NN, and Hybrid RRF (requires OpenSearch and the private corpus)
uv run python scripts/run_retrieval_benchmark.py --dataset-version 05082026

# Replay screening over the committed ranked-uid list (no OpenSearch, no model calls)
uv run python scripts/compose_retrieval_screening_gate.py

# CI floor: public ranked uids against baseline.json (no OpenSearch)
uv run pytest benchmarks/retrieval/test_retrieval_smoke.py::test_committed_hybrid_ranking_meets_baseline

# Maintainer re-index. Skips when the private corpus is absent.
uv run pytest benchmarks/retrieval/test_retrieval_smoke.py::test_hybrid_gating_meets_baseline
```
