# Retrieval Gating Benchmark Report — {dataset_version}

- Timestamp: {timestamp}
- Dataset version: {dataset_version}
- Candidate username: {candidate_username}
- Total corpus size: {n_corpus}
- Fitting jobs: {n_fitting} (Good: {n_good}, Moderate: {n_moderate}, Low: {n_low})
- Evaluation focus: Retrieval gating efficiency & fitting job retention

## Headline Production Gating Metrics (K=20 default)

| Mode | Good Recall@20 | Fitting Recall@20 | Naive Recall@20 | Reduction Rate | LLM Calls Saved | MRR |
|---|---|---|---|---|---|---|
{headline_table}

## Multi-Cutoff Evaluation Sweep (K in [20, 50, 90, 100, 150])

{cutoff_table}

## Interpretation Guide for Retrieval Gating

### 1. Gating Function & Production Goal
The primary objective of the retrieval tier during batch orchestration (`build_pairs` in `orchestration/nodes/batch.py`) is to act as a **high-recall filter gate**.
Instead of assessing all {n_corpus} postings with expensive LLMs ($O(\text{{users}} \times \text{{jobs}})$), retrieval reduces the candidate pool to top-$K$ while preserving fitting jobs:
- **Good Recall@K:** Fraction of the {n_good} top-tier jobs captured in top-$K$.
- **Fitting Recall@K:** Fraction of all {n_fitting} viable jobs (Good + Moderate) captured in top-$K$.
- **Naive Recall@K:** Expected recall if a sample of $K$ postings was drawn uniformly at random without replacement ($\frac{{\min(K, N)}}{{N}}$). It serves as the baseline to evaluate how much value (lift) the retrieval algorithm adds over random sampling.
- **Reduction Rate:** Percentage of downstream LLM calls eliminated: $\frac{{N - K}}{{N}}$.
- **LLM Calls Saved:** Total LLM evaluation calls eliminated per pipeline cycle for this candidate.

### 2. Multi-Cutoff Trade-Off Analysis
- **K=20 (Production Default):** Achieves **93.3% reduction** in LLM workload (saving 280 calls out of 300). Focuses on high precision for the best-matching opportunities.
- **K=50:** Achieves **83.3% reduction** (saving 250 calls) while expanding coverage of moderate fit postings.
- **K=90:** Matches the total count of fitting jobs ({n_fitting}). Evaluates retrieval sensitivity when the window size equals total viable volume.
- **K=100 & K=150:** Wider gating windows providing maximum safety margin against dropping viable positions while still cutting LLM costs by 50% to 67%.
