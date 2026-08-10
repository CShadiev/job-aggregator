# Screening Benchmark

Offline benchmark for `ScreeningAgent`: decide whether a posting is worth a full
fit assessment (`worth_full_assessment`) from CV + job only, and measure binary
classification against gold derived from historical CV ATS categories.

Planning doc: [`docs/planning/screening-agent.md`](../../docs/planning/screening-agent.md)

## Positive class

Gold `worth_full_assessment=true` iff historical `cv_category` ∈ {`moderate`,
`good`} (i.e. `cv_ats_match_score ≥ 50`). Low (`< 50`) is negative.

| Category   | Score range        | Binary gold |
| ---------- | ------------------ | ----------- |
| `low`      | `0 ≤ score < 50`   | `false`     |
| `moderate` | `50 ≤ score < 70`  | `true`      |
| `good`     | `70 ≤ score ≤ 100` | `true`      |

Dataset size is fixed at **300** entries: **30 good / 60 moderate / 210 low**.

## Layout

```text
benchmarks/screening/
  dataset/<DDMMYYYY>/   # git-tracked version (entries, manifest, CV — no profile)
  reports/              # gitignored — generated per run
```

New exports should be **committed** as a new (or same-day overwritten) version
directory under `dataset/`.

## Export dataset

Requires Mongo + S3 credentials (same env as the app). Default version is today's
**UTC** date as `DDMMYYYY`. Aborts if any band cannot meet its quota.

```bash
uv run python scripts/export_screening_benchmark_dataset.py
# optional:
#   --dataset-version 05082026
#   --username USER
#   --n 300   # must be 300 in v1
```

Then commit the new/updated `dataset/<DDMMYYYY>/` tree.

## Run benchmark

No Mongo at run time — only model API keys. Pass `--dataset-version` when more
than one version exists. Default model is `gpt-5.6-luna`.

```bash
uv run run-screening-benchmark --dataset-version 05082026
# smoke:
#   --limit 2
# optional:
#   --model gpt-5.6-luna
#   --concurrency 10
```

Writes `reports/<YYYYMMDD_HHMMSS>_<model>.md` and `.results.jsonl`. Headline
metrics are positive-class precision / recall / F1 (exact accuracy is secondary).
Confidence is captured for exploration only. Exit code is 0 on successful
completion even if metrics are poor; non-zero only for operational failures (or
>20% per-entry agent errors).
