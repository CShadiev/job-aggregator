# Fit Assessment Benchmark

Offline benchmark for `FitAssessmentAgent`: re-assess a frozen dataset and measure
how well the CV score gate reduces downstream cover-letter generation while
retaining fitting jobs. Category agreement (exact / adjacent accuracy) remains
as a diagnostic.

Planning doc: [`docs/planning/fit-assessment-benchmark.md`](../../docs/planning/fit-assessment-benchmark.md)

## Evaluation Objective & Ground Truth

Production (`route_after_assess`) sends a pair to cover-letter generation iff
`cv_ats_match_score >= COVER_LETTER_MIN_CV_SCORE` (default **80**). Gold bands
are historical ATS categories on the **CV** score (same thresholds as screening
and retrieval):

| Category   | Score range        | Cover-letter gold at t=80 |
| ---------- | ------------------ | ------------------------- |
| `low`      | `0 ≤ score < 50`   | should not pass           |
| `moderate` | `50 ≤ score < 70`  | viable / Fitting Recall   |
| `good`     | `70 ≤ score ≤ 100` | top-tier / Good Recall    |

A gold-Good job scored 70–79 will not pass production even if the model
reproduces gold exactly — the category floor (70) is below the cover-letter
gate (80).

The frozen dataset is **100** entries, stratified on **profile** category
(33 good / 33 moderate / 34 low). Gating metrics still use gold **CV**
categories, which may differ slightly from the profile mix.

## Layout

```text
benchmarks/fit_assessment/
  dataset/<DDMMYYYY>/   # git-tracked version (entries, manifest, profile, CV)
  reports/              # gitignored — generated per run
  metrics.py            # category agreement + cover-letter gating sweep
```

New exports should be **committed** as a new (or same-day overwritten) version
directory under `dataset/`.

## Metrics

Headline production metrics use CV-score threshold **t=80**. A sweep then
recomputes the same metrics at `t ∈ [50, 70, 80, 90]`, where an entry passes
iff `predicted_cv_score >= t`. `None` predictions never pass.

- **Good Recall:** Fraction of gold-CV-Good jobs that passed the gate.
- **Moderate Recall:** Fraction of gold-CV-Moderate jobs that passed (sweep only).
- **Fitting Recall:** Fraction of gold-CV Good ∪ Moderate jobs that passed.
- **Naive Recall:** Expected recall if a keep-set of the same size were drawn
  uniformly at random (`n_passed / N`).
- **Reduction Rate:** Percentage of cover-letter calls avoided:
  `(N - n_passed) / N`.
- **LLM Calls Saved:** Cover-letter generations avoided on this dataset.
- **Cost per 100:** Fit assessment's own USD spend from summed
  prompt/completion tokens × static `DEFAULT_RATES`, normalized to 100
  completed entries. Constant across score cutoffs. Unknown models report $0.

Exact / adjacent accuracy, confusion matrices, and per-class P/R/F1 for both
CV and profile scores remain in a diagnostics section.

## Export dataset

Requires Mongo + S3 credentials (same env as the app). Default version is today's
**UTC** date as `DDMMYYYY`.

```bash
uv run python scripts/export_fit_assessment_benchmark_dataset.py
# optional:
#   --dataset-version 01082026
#   --n 100
#   --username USER
```

Then commit the new/updated `dataset/<DDMMYYYY>/` tree.

## Run benchmark

No Mongo at run time — only model API keys. Pass `--dataset-version` when more
than one version exists. Default model is `grok-4.3`.

```bash
uv run run-fit-assessment-benchmark --dataset-version 01082026
# smoke:
#   --limit 2
# optional:
#   --model grok-4.3
#   --concurrency 10
```

Writes `reports/<YYYYMMDD_HHMMSS>_<model>.md` and `.results.jsonl`. Report
filenames do **not** include the dataset version (it is recorded in the report
body and results metadata). Headline metrics are cost per 100, reduction,
LLM calls saved, and naive / good / fitting recall at t=80. Exit code is 0 on
successful completion even if metrics are poor; non-zero only for operational
failures (or >20% per-entry agent errors).
