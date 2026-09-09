# Screening Benchmark Report — {dataset_version}

- Timestamp: {timestamp}
- Model: {model}
- Dataset version: {dataset_version}
- Dataset path: {dataset_path}
- Candidate username: {username}
- Entries evaluated: {n} (dataset n={n_entries}, completed={completed}, failed={failed})
- Fitting jobs: {n_fitting} (Good: {n_good}, Moderate: {n_moderate}, Low: {n_low})
- Concurrency: {concurrency}
- Evaluation focus: Screening gate efficiency & fitting job retention
- Exported at: {exported_at}

## Headline Production Screening Metrics (t=0.0, confidence unused)

| Cost per 100 | Reduction Rate | LLM Calls Saved | Naive Recall | Good Recall | Fitting Recall |
|---|---|---|---|---|---|
{headline_table}

{cost_note}

## Confidence-Threshold Sweep (t in [0.0, 0.5, 0.7, 0.8, 0.9, 0.95])

{sweep_table}

## Interpretation Guide for Screening Gating

### 1. Gating Function & Production Goal
The primary objective of the screening tier (`screen` → `route_after_screen` in `orchestration/routing.py`) is to act as a **high-recall filter gate**.
Instead of sending all {n} postings to expensive fit assessment, screening drops obvious non-fits while retaining viable jobs:
- **Good Recall:** Fraction of the {n_good} top-tier jobs that still reach fit assessment.
- **Fitting Recall:** Fraction of all {n_fitting} viable jobs (Good + Moderate) that still reach fit assessment.
- **Naive Recall:** Expected recall if a keep-set of the same size were drawn uniformly at random (`n_passed / N`). Lift over this baseline is the value the screener adds.
- **Reduction Rate:** Percentage of downstream fit-assessment calls eliminated: `(N - n_passed) / N`.
- **LLM Calls Saved:** Fit-assessment calls avoided for this candidate on this dataset.
- **Cost per 100:** Screening's own USD spend, normalized to 100 completed entries (static `DEFAULT_RATES`; no Mongo). Independent of the confidence cutoff.

Production routing currently ignores confidence: an entry passes iff `worth_full_assessment` is true (`t = 0.0`).

### 2. Confidence-Threshold Trade-Off
Raising `t` is a hypothetical second gate: pass only predicted-keeps whose confidence is at least `t`.
- **t=0.0 (Production Default):** Same as the binary keep/drop decision. Maximum recall; reduction comes only from predicted drops.
- **Higher t:** Additional predicted-keeps are held back, increasing reduction and lowering Good / Fitting Recall. Screening's own cost per 100 does not change.

Existing model confidence often clusters high, so early cutoffs may be flat — that is evidence that confidence is a weak lever, not a reason to pick cutoffs from the run.

## Diagnostics

### Binary classification

| Metric | Value |
|---|---|
| positive precision | {positive_precision} |
| positive recall | {positive_recall} |
| positive F1 | {positive_f1} |
| exact accuracy | {exact_accuracy} |

{confusion_matrix}

### Per gold band (cv_category)

{band_table}

### Confidence (exploratory)

- overall: n={conf_overall_n}, mean={conf_overall_mean}, p50={conf_overall_p50}
- among correct: n={conf_correct_n}, mean={conf_correct_mean}
- among incorrect: n={conf_incorrect_n}, mean={conf_incorrect_mean}
- by gold band: {conf_by_band}

### Token usage

- completed requests: {requests}
- input_tokens: {input_tokens}
- output_tokens: {output_tokens}
- total_tokens: {total_tokens}
- total screening USD: {total_usd}

### Stratification (dataset)

- axis: {strat_axis}
- positive_definition: {positive_definition}
- target_per_class: {strat_target}
- actual_per_class: {strat_actual}
