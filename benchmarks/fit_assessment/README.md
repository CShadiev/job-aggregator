# Fit Assessment Benchmark

Offline benchmark for `FitAssessmentAgent`: re-assess a frozen dataset and measure
how well predicted ATS score **categories** match historical gold categories.

Planning doc: [`docs/planning/fit-assessment-benchmark.md`](../../docs/planning/fit-assessment-benchmark.md)

## Categories

| Category   | Score range        |
| ---------- | ------------------ |
| `low`      | `0 ≤ score < 50`   |
| `moderate` | `50 ≤ score < 70`  |
| `good`     | `70 ≤ score ≤ 100` |

## Layout

```text
benchmarks/fit_assessment/
  dataset/<DDMMYYYY>/   # git-tracked version (entries, manifest, profile, CV)
  reports/              # gitignored — generated per run
```

New exports should be **committed** as a new (or same-day overwritten) version
directory under `dataset/`.

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
than one version exists.

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
body and results metadata). Exit code is 0 on successful completion even if
metrics are poor; non-zero only for operational failures (or >20% per-entry
agent errors).
