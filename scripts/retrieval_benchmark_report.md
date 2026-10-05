# Retrieval Gating Benchmark Report — {dataset_version}

- Timestamp: {timestamp}
- Dataset version: {dataset_version}
- Candidate username: {candidate_username}
- Total corpus size: {n_corpus}
- Fitting jobs: {n_fitting} (Good: {n_good}, Moderate: {n_moderate}, Low: {n_low})
- Production operating point: K={operating_k} (`PIPELINE_RETRIEVAL_RATIO` default 0.5 on this corpus)
- Evaluation focus: Retrieval gating efficiency & fitting job retention

## Headline Production Gating Metrics (K={operating_k})

| Mode | Good Recall@{operating_k} | Fitting Recall@{operating_k} | Naive Recall@{operating_k} | Reduction Rate | LLM Calls Saved | MRR |
|---|---|---|---|---|---|---|
{headline_table}

## Multi-Cutoff Evaluation Sweep (K in [20, 50, 90, 100, 150])

{cutoff_table}

## Interpretation Guide for Retrieval Gating

### 1. Gating Function & Production Goal
The primary objective of the retrieval tier during batch orchestration (`build_pairs` in `orchestration/nodes/batch.py`) is to act as a **high-recall filter gate**.
Instead of assessing all {n_corpus} postings with expensive LLMs, retrieval reduces the candidate pool to top-$K$ while preserving fitting jobs:
- **Good Recall@K:** Fraction of the {n_good} top-tier jobs captured in top-$K$.
- **Fitting Recall@K:** Fraction of all {n_fitting} viable jobs (Good + Moderate) captured in top-$K$.
- **Naive Recall@K:** Expected recall if a sample of $K$ postings was drawn uniformly at random without replacement ($\frac{{\min(K, N)}}{{N}}$). It serves as the baseline to evaluate how much value (lift) the retrieval algorithm adds over random sampling.
- **Reduction Rate:** Percentage of downstream LLM calls eliminated: $\frac{{N - K}}{{N}}$.
- **LLM Calls Saved:** Total LLM evaluation calls eliminated per pipeline cycle for this candidate.

### 2. Multi-Cutoff Trade-Off Analysis
- **K={operating_k} (production operating point):** Headline table. On this corpus `PIPELINE_RETRIEVAL_RATIO=0.5` selects this cutoff (`orchestration/retrieval.py`).
- **K=20:** Sweep row only. A tight top-K is not the production gate.
- **K=50 and K=90:** Intermediate windows. K=90 matches the fitting-job count ({n_fitting}) on this corpus.
- **K=100:** Wider sweep row between the fitting-count window and the production cutoff.
