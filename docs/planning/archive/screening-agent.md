# Screening Agent + Benchmark

## Overview

Add a lightweight **screening agent** that, given only a CV and a job posting,
decides whether the posting is worth a later full fit assessment
(`worth_full_assessment`) and attaches a calibrated `confidence`. The goal is
cost optimization: cheaply drop obvious non-fits before the expensive
profile+CV fit-assessment step. This plan covers the agent implementation and
an offline benchmark (skewed 300-entry dataset mirroring production imbalance).
**Pipeline wiring is out of scope.**

---

## Requirements

**In scope**

- `ScreeningAgent` (PydanticAI) with CV + job inputs only — no user profile.
- Minimal structured output: binary keep/drop decision + confidence; no
  summary, deal breakers, or continuous fit scores.
- Wire-format output uses `0` / `1` for the decision; public Python API exposes
  `bool`.
- Default model: `gpt-5.6-luna` (`Model.LUNA_5_6`).
- Versioned frozen benchmark dataset under
  `benchmarks/screening/dataset/<DDMMYYYY>/` with **exactly** 300 entries:
  **30 good / 60 moderate / 210 low** by historical `cv_ats_match_score`
  category (same band thresholds as fit assessment).
- Gold binary label derived as `true` iff category ∈ {moderate, good}
  (i.e. CV score ≥ 50).
- Offline runner: concurrent screening, binary classification metrics (P/R/F1
  primary under imbalance), confidence **captured** for exploration (not a
  quality gate), markdown report + results JSONL.
- Unit tests for pure metric/label helpers only (no LLM).

**Out of scope / non-goals**

- Integrating the agent into `workers/job_processing.py` or changing pipeline
  stages / Mongo schemas.
- Evaluating confidence quality as a scored metric (capture + report
  summaries only).
- Human labels, skip/applied signals, multi-user datasets.
- Soft exit-code quality thresholds / CI gates.
- Changing `FitAssessmentAgent` behavior or prompts.
- Soft fill when a band is short — inventory was verified (≥392 good, ≥492
  moderate, ≥1898 low joinable); export **aborts** if exact quotas cannot be
  met.

---

## Design decisions

### 1. Name: screening (not CV-prefilter)

**Chosen:** `ScreeningAgent` / `screening` package paths. Inputs happen to be
CV-only today; the name does not hard-code “CV” so the input surface can evolve
without a rename.

**Rejected:** `cv_prefilter` / `cv_screening` — premature coupling to input
modality.

### 2. Binary keep decision, not a continuous fit score

**Chosen:** Single boolean decision `worth_full_assessment` meaning “send to
full fit assessment.” Positive gold = historical CV category **moderate or
good** (`cv_ats_match_score ≥ 50`). Low (`< 50`) is negative.

**Rejected:** Emitting a 0–100 fit score (redundant with full assessment and
costs more output tokens). **Rejected for v1:** positive = good-only (≥70) —
too aggressive for a first gate; revisit later if precision is the bottleneck.

### 3. Wire format `0`/`1`, Python `bool`

**Chosen:** LLM structured output schema uses `Literal[0, 1]` (or equivalent
constrained int). `ScreeningAgent.screen` returns a public `ScreeningResult`
with `worth_full_assessment: bool` (`1 → True`, `0 → False`). Confidence is
`float` in `[0, 1]` on both layers.

**Why:** Some providers are flaky with JSON booleans (`true`/`True`/`yes`);
integer 0/1 is more robust. Callers still get a proper `bool`.

**Rejected:** Public API exposing `int` 0/1. **Rejected:** Prompt-only
instruction with schema-typed `bool` (schema would fight the prompt).

### 4. Confidence: capture only

**Chosen:** Require `confidence ∈ [0, 1]` = model’s confidence that
`worth_full_assessment` is correct (worthiness of full assessment). Benchmark
records it and reports exploratory summaries (means / quantiles by
correctness and by gold band). **Not** used in headline quality metrics or
thresholds.

**Rejected for v1:** Confidence-based abstention metrics or expected
calibration error as a gate.

### 5. Gold from historical `cv_ats_match_score` (same semantics)

**Chosen:** Export gold continuous CV score + category from stored
`FitAssessment` documents (same circular baseline as the fit-assessment
benchmark). Binary gold = `category_to_worth(cv_category)`. Prompt semantics
should match “CV-only initial screening” so historical CV scores remain a
meaningful teacher.

**Rejected:** Separate human labeling pass for v1.

### 6. Category bands reused; dataset skewed

**Chosen:** Reuse `benchmarks.fit_assessment.categories` (`low` / `moderate` /
`good`, thresholds 50 / 70). Stratify export to **exactly** 30 / 60 / 210.
Import shared helpers rather than duplicating band logic.

**Rejected:** Soft fill / `n < 300` — abort instead (inventory confirmed sufficient on `cshadiev`).

### 7. Metrics under class imbalance

**Chosen headline (in order):**

1. Positive-class precision / recall / F1 (`worth_full_assessment=true`)
2. Binary confusion matrix (gold × pred, plus `error` column if needed)
3. Exact binary accuracy (secondary — easy to inflate by always saying no)
4. Per–gold-band breakdown: for each of `low` / `moderate` / `good`, fraction
   correctly classified under the binary mapping (and counts)
5. Confidence exploration: mean (± optional p25/p50/p75) overall, among
   correct vs incorrect, and by gold band — **descriptive only**

**Rejected:** Adjacent accuracy (not meaningful for binary). **Rejected:**
Exact accuracy as the primary headline.

### 8. Layout mirrors fit-assessment benchmark

```text
agents/screening.py
agents/prompt_templates/screening.md
models/screening.py
benchmarks/screening/
  dataset/<DDMMYYYY>/
    manifest.json
    entries.jsonl
    cv.pdf                 # no profile.json — unused by agent
  reports/                 # gitignored
scripts/
  export_screening_benchmark_dataset.py
  run_screening_benchmark.py
  screening_benchmark_report.md
docs/planning/screening-agent.md
tests/unit/test_screening_benchmark_metrics.py
```

Default CLI model: `gpt-5.6-luna`. Concurrency: `Semaphore(10)` + `TaskGroup`.
Report filenames: `<YYYYMMDD_HHMMSS>_<model_slug>.*` (dataset version in body
only). Report-only exit 0; abort if >20% per-entry failures.

### 9. Default model

**Chosen:** `Model.LUNA_5_6` (`gpt-5.6-luna`) for agent construction examples
and benchmark CLI default — cheapest suitable option already registered in
`ModelFactory`. No new model enum entry required.

**Rejected:** `gpt-5.6-sol` (not available / not intended). Production
pipeline default remains undecided until integration.

---

## Resolved open questions

| # | Question | Resolution |
|---|---|---|
| 1 | Naming | `screening` / `ScreeningAgent` — do not encode CV in the name |
| 2 | Score vs binary | Binary `worth_full_assessment`; no continuous fit score |
| 3 | Positive class | moderate ∪ good (`cv_ats_match_score ≥ 50`) |
| 4 | Wire vs Python type | LLM outputs `0`/`1`; public API `bool` |
| 5 | Confidence | `[0, 1]`; capture + exploratory report stats; not scored as a gate |
| 6 | Category bands | Reuse fit-assessment helpers unchanged |
| 7 | Default model | `gpt-5.6-luna` (`Model.LUNA_5_6`) |
| 8 | Export shortfall | Hard-require 30/60/210; abort otherwise (inventory verified) |
| 9 | Spec location | `docs/planning/screening-agent.md` |
| 10 | Pipeline integration | Deferred |
| 11 | Dataset profile.json | Omit — agent does not use profile |

---

## Interfaces / contracts

### Output models — `models/screening.py`

```python
from typing import Literal
from pydantic import BaseModel, Field


class ScreeningAgentOutput(BaseModel):
    """Structured LLM wire format (agent ``output_type``)."""

    worth_full_assessment: Literal[0, 1]
    """1 = keep for full assessment; 0 = drop."""

    confidence: float = Field(ge=0, le=1)
    """Confidence that ``worth_full_assessment`` is correct."""


class ScreeningResult(BaseModel):
    """Public return type from ``ScreeningAgent.screen``."""

    worth_full_assessment: bool
    confidence: float = Field(ge=0, le=1)
```

### Agent — `agents/screening.py`

```python
class ScreeningAgent:
    def __init__(self, model: models.Model): ...

    async def screen(self, cv: Path | bytes, job: JobPosting) -> ScreeningResult:
        """Screen *job* using CV only (*cv* as path or PDF bytes)."""
        ...
```

- Prompt template: `agents/prompt_templates/screening.md` with `{job_posting}`
  placeholder; CV attached as `BinaryContent` (same PDF path/bytes pattern as
  fit assessment).
- Job JSON include set: reuse the same `_JOB_FIELDS` as
  `FitAssessmentAgent` (`uid`, `source`, `title`, `company`, `location`,
  `remote`, `url`, `tags`, `description_raw`, `job_types`, `posted_at`).
- After `agent.run`, map `ScreeningAgentOutput` → `ScreeningResult`
  (`bool(worth_full_assessment)` is fine since values are 0/1).
- No profile argument. No retries config required for v1 (optional later).

### Prompt responsibilities (screening.md)

- Role: cheap initial screen — decide if full assessment is worthwhile.
- Inputs: CV (PDF) + job posting only; ignore any implied profile.
- Output: `worth_full_assessment` as **0 or 1**; `confidence` in **[0, 1]**.
- Positive (1) when the CV suggests moderate-or-better alignment with the role
  (roughly: would not be an obvious reject at CV screen). Negative (0) for
  clear mismatches / missing must-haves evidenced on the CV.
- Keep reasoning internal; do not emit summary text fields.
- Prefer `description_raw` as primary requirements source (same note as fit
  assessment).

### Label helpers — `benchmarks/screening/labels.py`

```python
from benchmarks.fit_assessment.categories import FitCategory, score_to_category


def category_to_worth(category: FitCategory) -> bool:
    """True iff category is moderate or good (CV score ≥ 50)."""
    return category != FitCategory.LOW


def score_to_worth(score: float) -> bool:
    return category_to_worth(score_to_category(score))
```

### Metrics — `benchmarks/screening/metrics.py`

```python
def binary_precision_recall_f1(
    gold: list[bool],
    pred: list[bool | None],
    *,
    positive: bool = True,
) -> dict[str, float]:
    """Precision/recall/F1/support for the positive class. None → FN if gold positive."""
    ...


def binary_accuracy(gold: list[bool], pred: list[bool | None]) -> float: ...


def binary_confusion_matrix(
    gold: list[bool],
    pred: list[bool | None],
) -> dict[str, dict[str, int]]:
    """Rows/cols: ``true``, ``false``, optional ``error`` column."""
    ...


def band_binary_accuracy(
    gold_categories: list[FitCategory],
    gold_worth: list[bool],
    pred: list[bool | None],
) -> dict[str, dict[str, float]]:
    """Per gold band: n, correct, accuracy under binary mapping."""
    ...


def confidence_summary(
    confidences: list[float | None],
    correct: list[bool | None],  # None where pred errored
    gold_categories: list[FitCategory],
) -> dict:
    """Exploratory means (and simple quantiles) overall / by correctness / by band."""
    ...
```

### Dataset entry (`entries.jsonl` line)

```json
{
  "id": "0",
  "username": "<username>",
  "job": { "...": "same _JOB_FIELDS (+ JobPosting validate fields as export needs)" },
  "gold": {
    "cv_ats_match_score": 62.0,
    "cv_category": "moderate",
    "worth_full_assessment": true
  }
}
```

Do **not** store profile scores, deal breakers, or summary in screening gold
(irrelevant to this agent). Historical CV score + category remain for
analysis and band breakdowns.

### Manifest (`manifest.json`)

```json
{
  "schema_version": 1,
  "dataset_version": "DDMMYYYY",
  "exported_at": "ISO-8601",
  "username": "...",
  "n_entries": 300,
  "stratification": {
    "axis": "cv_category",
    "target_per_class": {"low": 210, "moderate": 60, "good": 30},
    "actual_per_class": {"low": 210, "moderate": 60, "good": 30},
    "positive_definition": "cv_category in {moderate, good} (score >= 50)"
  },
  "cv_path": "cv.pdf",
  "source": {
    "mongodb_database": "...",
    "note": "CV scores are historical FitAssessmentAgent outputs, not human labels. Binary gold derived from cv_category."
  }
}
```

No `profile_path`. `dataset_version` must equal the parent directory name.

### Export CLI

```text
uv run python scripts/export_screening_benchmark_dataset.py
  [--dataset-root benchmarks/screening/dataset]
  [--dataset-version DDMMYYYY]   # default: today's UTC date as DDMMYYYY
  [--n 300]                      # must equal sum of quotas; default 300
  [--username USER]
```

Quotas are fixed ratios of `n` only if explicitly redesigned later; **v1 hardcodes
30/60/210** and requires `--n 300` (or default 300). If `--n` ≠ 300, abort with
a clear error (avoid silent quota math for v1).

Behavior:

1. Resolve username (sole assessment username, or `--username`; fail if ambiguous).
2. Join latest assessment per `job_uid` to jobs (same aggregation pattern as
   fit-assessment export).
3. Bucket by `score_to_category(cv_ats_match_score)`.
4. If any band has fewer than its quota → **abort** with counts.
5. Sample exactly 30/60/210 (deterministic shuffle: seed from
   `dataset_version` string or fixed `seed=0` documented in script — prefer
   `seed=0` for simplicity).
6. Write `entries.jsonl`, `manifest.json`, `cv.pdf` (from S3 via
   `ObjectStorage.get_user_cv`). **No** `profile.json`.
7. Same-day re-export overwrites the version directory after a warning log.

### Runner CLI

```text
uv run python scripts/run_screening_benchmark.py
  [--dataset-root benchmarks/screening/dataset]
  [--dataset-version DDMMYYYY]
  [--reports-dir benchmarks/screening/reports]
  [--model gpt-5.6-luna]
  [--concurrency 10]
  [--limit N]
```

Also register `run-screening-benchmark` in `[project.scripts]`.

Behavior mirrors fit-assessment runner: resolve versioned dir; validate
manifest; no Mongo at run time; `ScreeningAgent(ModelFactory.get_model(...))`;
`screen(cv_path, job)` per entry; capture usage via `capture_run_messages` +
`RunUsage`; write report + JSONL; print report path; exit 0 unless operational
abort / >20% failures.

### Report skeleton

```markdown
# Screening Benchmark Report

- Timestamp / Model / Dataset version / path / n / username / concurrency
- Completed / Failed

## Headline

| Metric | Value |
|---|---|
| positive precision | … |
| positive recall | … |
| positive F1 | … |
| exact accuracy | … |

## Confusion matrix
(gold true/false × pred true/false [/ error])

## Per gold band (cv_category)
| band | n | binary gold | accuracy | …

## Confidence (exploratory)
- overall mean / p50
- mean among correct vs incorrect
- mean by gold band

## Cost
- requests / input_tokens / output_tokens / total_tokens

## Stratification
…
```

### Results JSONL

```json
{"type": "meta", "dataset_version": "...", "model": "gpt-5.6-luna", "timestamp": "..."}
```

```json
{
  "type": "result",
  "id": "0",
  "job_uid": "...",
  "gold": {
    "cv_ats_match_score": 62.0,
    "cv_category": "moderate",
    "worth_full_assessment": true
  },
  "predicted": {
    "worth_full_assessment": true,
    "confidence": 0.82
  },
  "error": null
}
```

On failure: `"predicted": null`, `"error": "..."`.

---

## Implementation plan

1. **Models** — add `models/screening.py` with `ScreeningAgentOutput` and
   `ScreeningResult` as specified.
2. **Prompt** — add `agents/prompt_templates/screening.md` (CV + job only;
   0/1 + confidence; no narrative fields).
3. **Agent** — add `agents/screening.py`: load prompt, build job JSON with
   shared field set, attach PDF, run with `output_type=ScreeningAgentOutput`,
   return converted `ScreeningResult`.
4. **Benchmark helpers**
   - `benchmarks/screening/__init__.py`
   - `benchmarks/screening/labels.py` (`category_to_worth`, `score_to_worth`)
   - `benchmarks/screening/metrics.py` (binary P/R/F1, accuracy, confusion,
     band breakdown, confidence summary)
   - `tests/unit/test_screening_benchmark_metrics.py` for helpers + label
     mapping (including boundary scores 49.9 / 50.0 / 69.9 / 70.0)
5. **Export script** — `scripts/export_screening_benchmark_dataset.py`
   (Mongo+S3; hard 30/60/210; write dataset tree without profile).
6. **Report template** — `scripts/screening_benchmark_report.md`.
7. **Runner** — `scripts/run_screening_benchmark.py` (+
   `run-screening-benchmark` entry point in `pyproject.toml`).
8. **Git policy** — `.gitignore`: add `benchmarks/screening/reports/`.
   Commit helpers, scripts, plan, README, and each
   `dataset/<DDMMYYYY>/` tree after export (including `cv.pdf`).
9. **Operator docs** — `benchmarks/screening/README.md` (export/run commands,
   positive-class definition, link to this plan). Do not expand root README
   unless asked.
10. **Manual verification**
    - Export; confirm `n_entries=300` and exact stratification in manifest.
    - `run ... --limit 2` smoke test with default `gpt-5.6-luna`.
    - One full 300-entry run; confirm report headline + confidence section +
      cost block.

---

## Edge cases and error handling

| Case | Behavior |
|---|---|
| Band inventory &lt; quota | Export aborts with per-band available vs required counts |
| `--n` ≠ 300 | Export aborts (v1 fixed size) |
| Assessment without matching job | Skip; not in pool |
| Multiple usernames | Abort unless `--username` set |
| Missing CV in S3 at export | Abort export |
| Missing dataset files at run | Abort runner (non-zero) |
| `--dataset-version` omitted, &gt;1 dir | Abort with list of versions |
| Manifest version ≠ directory name | Abort runner |
| Single-entry agent exception | Record error; `predicted: null`; continue |
| &gt;20% entry failures | Abort non-zero; keep partial JSONL if any |
| LLM returns worth outside `{0,1}` | Pydantic validation failure → entry error |
| Confidence outside `[0,1]` | Validation failure → entry error |
| Re-export same `DDMMYYYY` | Overwrite version dir after warning |

---

## Assumptions and risks

**Assumptions**

- Single primary username (`cshadiev`) remains sufficient; inventory stays
  above quotas until export time.
- Historical `cv_ats_match_score` is a usable teacher for “worth full
  assessment” despite being produced by a different agent that also saw the
  profile in its prompt (CV score instructions were CV-only).
- PydanticAI + provider JSON schema honors `Literal[0, 1]` for the decision
  field.
- Omitting `profile.json` is acceptable; screening never needs it.

**Risks**

- **Label circularity / teacher mismatch:** full fit agent’s CV score may not
  perfectly match an independent CV-only screen — agreement ceilings may be
  modest; treat early runs as baselines, not absolute truth.
- **Imbalance gaming:** models that always predict `false` get ~70% accuracy;
  mitigate by leading with positive P/R/F1 in reports.
- **Moderate band ambiguity:** gold positives include moderate (50–70); false
  negatives there hurt recall and may over-filter in production later —
  monitor per-band accuracy.
- **Cost/latency:** 300 PDF-backed calls; use `--limit` and concurrency for
  iteration.
- **Sensitive artifacts:** CV + job text in git-tracked dataset — keep repo
  private.
- **Integration unknown:** thresholding on confidence or combining with other
  signals is deferred; avoid baking production gate logic into the agent API
  now.
