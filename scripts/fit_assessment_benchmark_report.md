# Fit Assessment Benchmark Report — {dataset_version}

- Timestamp: {timestamp}
- Model: {model}
- Dataset version: {dataset_version}
- Dataset path: {dataset_path}
- Candidate username: {username}
- Entries evaluated: {n} (dataset n={n_entries}, completed={completed}, failed={failed})
- Fitting jobs (gold CV): {n_fitting} (Good: {n_good}, Moderate: {n_moderate}, Low: {n_low})
- Concurrency: {concurrency}
- Evaluation focus: Cover-letter gate efficiency & fitting job retention
- Production CV threshold: {production_threshold}
- Exported at: {exported_at}

## Headline Production Cover-Letter Metrics (t={production_threshold}, cv_ats_match_score)

| Cost per 100 | Reduction Rate | LLM Calls Saved | Naive Recall | Good Recall | Fitting Recall |
|---|---|---|---|---|---|
{headline_table}

{cost_note}

## CV-Score Threshold Sweep (t in [50, 70, 80, 90])

{sweep_table}

## Interpretation Guide for Fit-Assessment Gating

### 1. Gating Function & Production Goal
The primary objective of the fit-assessment tier (`assess` → `route_after_assess` in `orchestration/routing.py`) is to decide which screened jobs are worth a **cover letter**.
Production routes to `cover_letter` iff `cv_ats_match_score >= COVER_LETTER_MIN_CV_SCORE` (default {production_threshold}). Gold bands below are historical CV categories (Good ≥ 70, Moderate ≥ 50), the same axis screening and retrieval use:
- **Good Recall:** Fraction of the {n_good} top-tier (gold CV Good) jobs that still receive a cover letter at this cutoff.
- **Fitting Recall:** Fraction of all {n_fitting} viable jobs (gold CV Good + Moderate) that still receive a cover letter.
- **Naive Recall:** Expected recall if a keep-set of the same size were drawn uniformly at random (`n_passed / N`). Lift over this baseline is the value the scorer adds.
- **Reduction Rate:** Percentage of downstream cover-letter calls eliminated: `(N - n_passed) / N`.
- **LLM Calls Saved:** Cover-letter generations avoided for this candidate on this dataset.
- **Cost per 100:** Fit assessment's own USD spend, normalized to 100 completed entries (static `DEFAULT_RATES`; no Mongo). Independent of the score cutoff.

A gold-Good job with a historical score of 70–79 will not pass the production gate even under a perfect reproduction of gold — that gap is real, not a metric bug.

### 2. Score-Threshold Trade-Off
Raising `t` is a stricter cover-letter gate on the predicted CV score.
- **t=50:** Pass moderate-or-better. Widest keep-set; matches the screening positive class.
- **t=70:** Pass the Good band. Aligns with category `good`.
- **t=80 (Production Default):** `COVER_LETTER_MIN_CV_SCORE`. Headline operating point.
- **t=90:** Stricter than production. Higher reduction, lower recall.

Fit assessment's own cost per 100 does not change with `t`.

## Diagnostics

### Category agreement

| Score | Exact accuracy | Adjacent accuracy |
|---|---|---|
| profile_ats_match_score | {profile_exact} | {profile_adjacent} |
| cv_ats_match_score | {cv_exact} | {cv_adjacent} |

### Profile — confusion matrix

{profile_confusion}

### Profile — per-class metrics

{profile_prf}

### CV — confusion matrix

{cv_confusion}

### CV — per-class metrics

{cv_prf}

### Token usage

- completed requests: {requests}
- input_tokens: {input_tokens}
- output_tokens: {output_tokens}
- total_tokens: {total_tokens}
- total fit-assessment USD: {total_usd}

### Stratification (dataset)

- axis: {strat_axis}
- target_per_class: {strat_target}
- actual_per_class: {strat_actual}
