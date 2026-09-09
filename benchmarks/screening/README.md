# Screening Benchmark

Offline benchmark for `ScreeningAgent`: decide whether a posting is worth a full
fit assessment (`worth_full_assessment`) from CV + job only. The report measures
how effectively the screening gate reduces downstream fit-assessment calls while
retaining fitting jobs.

Planning doc: [`docs/planning/screening-agent.md`](../../docs/planning/screening-agent.md)

## Evaluation Objective & Ground Truth

Gold `worth_full_assessment=true` iff historical `cv_category` ∈ {`moderate`,
`good`} (i.e. `cv_ats_match_score ≥ 50`). Low (`< 50`) is negative.

| Category   | Score range        | Binary gold | Role in gating |
| ---------- | ------------------ | ----------- | -------------- |
| `low`      | `0 ≤ score < 50`   | `false`     | Should be dropped |
| `moderate` | `50 ≤ score < 70`  | `true`      | Viable; counts toward Fitting Recall |
| `good`     | `70 ≤ score ≤ 100` | `true`      | Top-tier; counts toward Good Recall and Fitting Recall |

Dataset size is fixed at **300** entries: **30 good / 60 moderate / 210 low**
(90 fitting).

The agent remains binary (keep/drop + confidence). Production routing
(`route_after_screen`) ignores confidence: an entry passes iff
`worth_full_assessment` is true.

## Layout

```text
benchmarks/screening/
  dataset/<DDMMYYYY>/   # git-tracked version (entries, manifest, CV — no profile)
  reports/              # gitignored — generated per run
  metrics.py            # gating metrics (good/fitting recall, reduction, cost per 100)
```

New exports should be **committed** as a new (or same-day overwritten) version
directory under `dataset/`.

## Metrics

Headline production metrics use confidence threshold **t=0.0** (confidence unused,
matching production). A sweep then recomputes the same metrics at
`t ∈ [0.0, 0.5, 0.7, 0.8, 0.9, 0.95]`, where an entry passes iff predicted keep
and `confidence ≥ t`.

- **Good Recall:** Fraction of the 30 top-tier jobs that passed the gate.
- **Moderate Recall:** Fraction of the 60 moderate jobs that passed (sweep only).
- **Fitting Recall:** Fraction of all 90 viable jobs (Good + Moderate) that passed.
- **Naive Recall:** Expected recall if a keep-set of the same size were drawn
  uniformly at random (`n_passed / N`). Lift over this baseline is the value the
  screener adds.
- **Reduction Rate:** Percentage of downstream fit-assessment calls avoided:
  `(N - n_passed) / N`.
- **LLM Calls Saved:** Fit-assessment calls avoided on this dataset.
- **Cost per 100:** Screening's own USD spend from summed prompt/completion
  tokens × static `DEFAULT_RATES`, normalized to 100 completed entries. Constant
  across confidence cutoffs. Unknown models report $0.

Precision / F1 / exact accuracy, the confusion matrix, and per-band accuracy
remain in a diagnostics section. `None` predictions never pass (hurt recall,
increase reduction).

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
metrics are cost per 100, reduction, LLM calls saved, naive / good / fitting
recall. Exit code is 0 on successful completion even if metrics are poor;
non-zero only for operational failures (or >20% per-entry agent errors).
