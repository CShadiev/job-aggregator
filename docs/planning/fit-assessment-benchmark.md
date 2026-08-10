# Fit Assessment Agent Benchmark

## Overview

Build a reproducible offline benchmark for `FitAssessmentAgent` that measures how
well a candidate model/prompt reproduces **historical fit-score categories** on a
versioned, git-tracked 100-entry dataset (`dataset/<DDMMYYYY>/`) sampled from
production Mongo data for the single user in the system. The runner is a
standalone script (not pytest): it re-assesses each entry, compares predicted
categories to gold labels, and writes a markdown report under
`benchmarks/fit_assessment/reports/` for later comparison — report filenames stay
timestamp+model only; the dataset version is recorded inside the report. User
`skipped` / application signals are out of scope for this version.

---

## Requirements

**In scope**

- One-shot export script that builds a frozen 100-entry dataset version from
  Mongo + S3 into `dataset/<DDMMYYYY>/` (job fields, gold scores, profile, CV)
  and commits that tree to git.
- Stratified sampling across fit categories derived from historical
`profile_ats_match_score` (primary stratification axis), targeting a balanced
mix of low / moderate / good when inventory allows.
- Benchmark runner script that loads the frozen dataset, invokes
`FitAssessmentAgent.assess` for each entry, maps scores → categories, computes
metrics for both `cv_ats_match_score` and `profile_ats_match_score`, and writes
a markdown report (plus a machine-readable sidecar JSON of per-entry results).
- Report-only behavior: always exit 0 on successful completion even if metrics
are poor; non-zero only for operational failures (missing dataset, agent
errors that abort the run, I/O errors).

**Out of scope / non-goals**

- Using `skipped`, `applied`, or application stage as labels or metrics.
- Evaluating `deal_breakers` or `summary` quality (still capture raw outputs in
the per-entry JSON for future analysis).
- Pytest-based evaluation, CI gates, or soft pass/fail thresholds.
- Multi-user datasets or live Mongo sampling at benchmark time.
- Changing production `FitAssessmentAgent` behavior or prompts (benchmark only).

---



## Design decisions



### 1. Categorical ground truth (not continuous regression, not skip)

**Chosen:** Map each ATS score to `{low, moderate, good}` and score
**category agreement**.


| Category   | Score range        |
| ---------- | ------------------ |
| `low`      | `0 ≤ score < 50`   |
| `moderate` | `50 ≤ score < 70`  |
| `good`     | `70 ≤ score ≤ 100` |


Float-safe half-open intervals (except closed at 100):

```text
if score < 50: low
elif score < 70: moderate
else: good
```

Boundary points: `50.0` and `70.0` belong to the higher band (`moderate` /
`good`). Must be deterministic for both gold export and runner predictions.

**Rejected:** Continuous MAE/Spearman against historical scores — too sensitive
to systematic rescaling when prompts change. **Rejected for v1:** skip-based
ranking metrics — deferred until human-signal evaluation is designed.

### 2. Versioned frozen dataset snapshot

**Chosen:** Each export writes a new (or same-day overwrite) version under
`benchmarks/fit_assessment/dataset/<DDMMYYYY>/` (e.g. `01082026`). Dataset
versions are **committed to git** so benchmarks remain reproducible without
re-querying Mongo. The runner never queries Mongo for jobs/assessments/profile.

Report filenames stay `<timestamp>_<model_slug>.*` only — **do not** encode
the dataset version in the filename. The report **body** (and results JSONL
header/metadata) must record `dataset_version` (`DDMMYYYY`) and path.

**Rejected:** Live sampling each run — breaks cross-run comparability.
**Rejected:** Single unversioned dataset directory — cannot compare runs against
different gold snapshots over time.
**Rejected:** Encoding dataset version in report filenames — noisy; version
belongs in report metadata.

### 3. Stratification and single username

**Chosen:** Stratify primarily on **gold** `profile_ats_match_score` **category**,
aiming for as even a split as possible across the three bands (e.g. ~33/33/34).
If a band has fewer than the target count, take all available and fill the
remainder from other bands (prefer under-filled bands first; if still short,
document actual counts in `manifest.json` and proceed with `n < 100` only if
total inventory is under 100 — otherwise always emit exactly 100).

Secondary soft preference when choosing within a band: diversify
`cv_ats_match_score` categories when possible (not a hard quota).

Username: take the sole user from `user_profiles` (or the only username present
on assessments). Fail the export if multiple usernames exist with assessments
(forces an explicit choice later).

**Rejected:** Random sample (skewed toward whatever production scored most).
**Rejected:** Multi-user packaging (unnecessary today; complicates CV layout).

### 4. Metrics (report headline)

Evaluate **CV** and **profile** category predictions separately against gold
categories derived from historical scores stored in the dataset.


| Metric                            | Role                                                                                                    |
| --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Exact category accuracy           | Primary headline (profile first, then CV)                                                               |
| Confusion matrix (3×3)            | Error pattern diagnosis                                                                                 |
| Per-class precision / recall / F1 | Imbalance / band-specific regressions                                                                   |
| Adjacent accuracy                 | Softer: prediction equals gold **or** an immediate neighbor (low↔moderate, moderate↔good; not low↔good) |


Token/request usage (via `pydantic_ai` `capture_run_messages` / `RunUsage`, same
pattern as the deduplication benchmark) is logged in the report for cost
tracking, not as a quality metric.

**Rejected for v1:** Cohen’s kappa, continuous residual stats, deal-breaker
set metrics.

### 5. Layout and report-only runner

**Chosen paths**

```text
benchmarks/fit_assessment/
  dataset/
    <DDMMYYYY>/              # e.g. 01082026 — git-tracked dataset version
      manifest.json          # includes dataset_version, sampling stats, username, n
      entries.jsonl          # one JSON object per line (see contracts)
      profile.json           # frozen UserProfile
      cv.pdf                 # snapshot of the user's CV at export time
  reports/                   # gitignored — generated per run
    <YYYYMMDD_HHMMSS>_<model_slug>.md
    <YYYYMMDD_HHMMSS>_<model_slug>.results.jsonl
scripts/
  export_fit_assessment_benchmark_dataset.py
  run_fit_assessment_benchmark.py
docs/planning/
  fit-assessment-benchmark.md   # this document
```

`DDMMYYYY` = calendar date of the export in local/UTC as chosen at export time
(document which timezone in the export script log; prefer UTC date to avoid
ambiguity). Same calendar day re-export overwrites that version directory.

Shared category/metric helpers live under
`benchmarks/fit_assessment/` (e.g. `categories.py`, `metrics.py`) and are
imported by the scripts — not under `tests/`, since this is not a pytest suite.

**Rejected:** Soft exit-code thresholds (can be added later against a baseline
report). **Rejected:** Putting the dataset under `tests/datasets/` (that tree is
for pytest fixtures; this artifact is large and report-oriented).

### 6. Concurrency and model selection

Mirror production assessment: `asyncio.Semaphore(10)` + `TaskGroup` /
`gather` over entries. Model selected via CLI `--model` defaulting to
`grok-4.3` (`Model.GROK_4_3`), resolved through `ModelFactory`.

On per-entry agent failure: record the error in the results JSONL, count as
category mismatch (no predicted category), continue the run; do not abort the
whole benchmark unless failures exceed 20% of entries (then abort with non-zero
exit — likely systemic outage).

---



## Resolved open questions


| #   | Question                                   | Resolution                                                                                  |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------- |
| 1   | Ground truth: regression vs skip vs hybrid | Categorical fit bands from historical scores only; skip deferred                            |
| 2   | Frozen vs live dataset                     | Versioned freeze under `dataset/<DDMMYYYY>/`, git-tracked                                   |
| 3   | Sampling                                   | Stratify on profile score category; single username                                         |
| 4   | Metric set                                 | Category accuracy, confusion matrix, per-class P/R/F1, adjacent accuracy for CV and profile |
| 5   | Report behavior / paths                    | Report-only; filenames = timestamp+model only; dataset version in report body               |
| —   | Band boundaries for floats                 | `0 ≤ s < 50` low; `50 ≤ s < 70` moderate; `70 ≤ s ≤ 100` good                               |
| —   | Dataset VCS                                | Commit dataset versions; gitignore only `reports/`                                          |
| —   | `deal_breakers` / `summary`                | Captured in results JSONL only; not scored                                                  |
| —   | Multiple usernames at export               | Fail export if more than one username has assessments                                       |


---



## Interfaces / contracts



### Category helper

```python
# benchmarks/fit_assessment/categories.py
from enum import StrEnum

class FitCategory(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    GOOD = "good"

def score_to_category(score: float) -> FitCategory:
    """Map ATS score in [0, 100] to low / moderate / good."""
    ...
```



### Dataset entry (`entries.jsonl` line)

Each line is a JSON object:

```json
{
  "id": "0",
  "username": "<username>",
  "job": {
    "uid": "...",
    "source": "...",
    "title": "...",
    "company": "...",
    "location": "...",
    "remote": false,
    "url": "...",
    "tags": [],
    "description_raw": "...",
    "job_types": [],
    "posted_at": "2026-01-15T12:00:00Z"
  },
  "gold": {
    "cv_ats_match_score": 62.0,
    "profile_ats_match_score": 78.0,
    "cv_category": "moderate",
    "profile_category": "good",
    "deal_breakers": [],
    "summary": "..."
  }
}
```

`job` fields must match exactly what `FitAssessmentAgent` includes via
`_JOB_FIELDS` in `agents/fit_assessment.py` (plus whatever `JobPosting`
requires to `model_validate`). Gold categories are precomputed at export time
with `score_to_category` so the runner and export never disagree.

### Manifest (`manifest.json`)

```json
{
  "schema_version": 1,
  "dataset_version": "01082026",
  "exported_at": "ISO-8601",
  "username": "...",
  "n_entries": 100,
  "stratification": {
    "axis": "profile_category",
    "target_per_class": {"low": 34, "moderate": 33, "good": 33},
    "actual_per_class": {"low": 34, "moderate": 33, "good": 33}
  },
  "cv_path": "cv.pdf",
  "profile_path": "profile.json",
  "source": {
    "mongodb_database": "...",
    "note": "Scores are historical FitAssessmentAgent outputs, not human labels."
  }
}
```

`dataset_version` must equal the parent directory name (`DDMMYYYY`).

### Export script CLI

```text
uv run python scripts/export_fit_assessment_benchmark_dataset.py
  [--dataset-root benchmarks/fit_assessment/dataset]
  [--dataset-version DDMMYYYY]   # default: today's UTC date as DDMMYYYY
  [--n 100]
  [--username USER]              # optional; default = sole username with assessments
```

Behavior:

1. Resolve `out_dir = <dataset-root>/<dataset-version>/`.
2. Connect via existing `ConfigProvider` + `AsyncMongoClient` / collections
   (`assessments`, `jobs`, `user_profiles`) and `ObjectStorage.get_user_cv`.
3. Join assessments to jobs for the username; drop rows missing job documents.
4. Assign `profile_category` from gold profile score; stratified sample to `n`.
5. Write `entries.jsonl`, `manifest.json`, `profile.json`, and `cv.pdf` into
   `out_dir`.
6. If `out_dir` already exists, overwrite after a warning log (same-day refresh).

Reuse repository helpers where practical; a thin aggregation in the script is
acceptable if `MongoJobsRepository` lacks a suitable join API — do **not**
expand the public repository API unless a small read helper clearly pays for
itself (e.g. `get_assessments_with_jobs(username)`). Prefer keeping export
logic in the script over growing the repo for a one-shot tool.

### Benchmark runner CLI

```text
uv run python scripts/run_fit_assessment_benchmark.py
  [--dataset-root benchmarks/fit_assessment/dataset]
  [--dataset-version DDMMYYYY]   # required if multiple versions exist;
                                 # if omitted and exactly one version dir → use it;
                                 # if omitted and several → abort with list of versions
  [--reports-dir benchmarks/fit_assessment/reports]
  [--model grok-4.3]
  [--concurrency 10]
  [--limit N]                    # optional: first N entries (smoke runs)
```

Behavior:

1. Resolve `dataset_dir = <dataset-root>/<dataset-version>/`; load manifest,
   entries, `profile.json`, `cv.pdf`. Runner needs **no Mongo** — only API keys
   for the model. Abort if `manifest.dataset_version` ≠ directory name.
2. Construct `FitAssessmentAgent(ModelFactory.get_model(...))`.
3. Assess all entries with the configured concurrency.
4. Compute metrics; write `reports/<timestamp>_<model_slug>.md` and
   `.results.jsonl` (**filename does not include dataset version**).
5. Report body and results metadata must include `dataset_version`.
6. Print the report path to stdout; exit 0 if the run completed (even with
   per-entry failures below the 20% abort threshold).

### Report markdown skeleton

```markdown
# Fit Assessment Benchmark Report

- Timestamp: ...
- Model: ...
- Dataset version: DDMMYYYY
- Dataset path: benchmarks/fit_assessment/dataset/DDMMYYYY
- Dataset: n=..., username=..., exported_at=...
- Concurrency: ...
- Completed: k/n  Failed: f

## Headline

| Score | Exact accuracy | Adjacent accuracy |
|---|---|---|
| profile_ats_match_score | … | … |
| cv_ats_match_score | … | … |

## Profile — confusion matrix
(... gold rows × predicted cols: low, moderate, good; plus "error" column if any)

## Profile — per-class metrics
| class | precision | recall | f1 | support |

## CV — confusion matrix
...

## CV — per-class metrics
...

## Cost
- requests / input_tokens / output_tokens / total_tokens

## Stratification (dataset)
...
```



### Results JSONL

First line is a metadata record (not an entry result):

```json
{"type": "meta", "dataset_version": "01082026", "model": "grok-4.3", "timestamp": "..."}
```

Subsequent lines are per-entry results:

```json
{
  "type": "result",
  "id": "0",
  "job_uid": "...",
  "gold": {"cv_ats_match_score": 62.0, "profile_ats_match_score": 78.0,
           "cv_category": "moderate", "profile_category": "good"},
  "predicted": {"cv_ats_match_score": 60.0, "profile_ats_match_score": 75.0,
                "cv_category": "moderate", "profile_category": "good",
                "deal_breakers": [], "summary": "..."},
  "error": null
}
```



### Metrics helpers

```python
# benchmarks/fit_assessment/metrics.py
def exact_accuracy(gold: list[FitCategory], pred: list[FitCategory | None]) -> float: ...
def adjacent_accuracy(gold: list[FitCategory], pred: list[FitCategory | None]) -> float: ...
def confusion_matrix(...) -> dict[str, dict[str, int]]: ...
def per_class_prf(...) -> dict[FitCategory, dict[str, float]]: ...
```

`None` prediction (agent error) never counts as a match; included in support
denominators for accuracy (i.e. accuracy = correct / n_entries).

---



## Implementation plan

1. **Add package layout**
  - Create `benchmarks/fit_assessment/__init__.py` (empty).
  - Implement `benchmarks/fit_assessment/categories.py` with `FitCategory` and
  `score_to_category`.
  - Implement `benchmarks/fit_assessment/metrics.py` with exact/adjacent
  accuracy, confusion matrix, per-class P/R/F1.
  - Optionally add a tiny unit test file
  `tests/unit/test_fit_assessment_benchmark_metrics.py` for pure helpers
  only (no LLM) — allowed and recommended; the **runner itself** stays a
  script.
2. **Export script** — `scripts/export_fit_assessment_benchmark_dataset.py`
  - Wire config, Mongo, S3.
  - Resolve `--dataset-version` (default UTC today as `DDMMYYYY`).
  - Resolve username; fail if ambiguous.
  - Join assessments ↔ jobs; build candidate pool with categories.
  - Stratified sample to `--n` (default 100).
  - Write into `dataset/<DDMMYYYY>/`: `entries.jsonl`, `manifest.json`,
    `profile.json`, `cv.pdf`.
  - Log version id and actual per-class counts.
3. **Runner script** — `scripts/run_fit_assessment_benchmark.py`
  - argparse for dataset-root/version, reports, model, concurrency, limit.
  - Resolve versioned dataset dir; validate manifest `dataset_version`.
  - Load dataset artifacts (no Mongo).
  - Concurrent `FitAssessmentAgent.assess(profile, cv_path, job)`.
  - Map predictions through `score_to_category`; compute metrics.
  - Capture usage via `capture_run_messages` + `RunUsage`.
  - Write markdown report + results JSONL (filenames: timestamp + model only);
    embed `dataset_version` in report body / results metadata; log path.
4. **Git policy**
  - `.gitignore`: `benchmarks/fit_assessment/reports/` only (generated).
  - **Commit** helpers, scripts, plan, and each `dataset/<DDMMYYYY>/` tree
    (including `cv.pdf` / `entries.jsonl` / `profile.json`) after export.
  - Document in `benchmarks/fit_assessment/README.md` that new exports should be
    committed as a new (or same-day updated) version directory.
5. **Smoke documentation**
  - In `benchmarks/fit_assessment/README.md`: export command, run command with
    `--dataset-version`, category definitions, pointer to this planning doc.
  - Do not expand root `README.md` unless asked.
6. **Manual verification (implementer)**
  - Export against local/dev Mongo; confirm version dir, `n_entries`, stratification.
  - `run ... --dataset-version <DDMMYYYY> --limit 2` smoke test.
  - Full 100-entry run once; confirm report body lists dataset version and
    filenames do not.

---



## Edge cases and error handling


| Case                                | Behavior                                                                |
| ----------------------------------- | ----------------------------------------------------------------------- |
| Fewer than 100 joinable assessments | Export all; `manifest.n_entries` reflects reality; warn                 |
| Empty band (e.g. no `low`)          | Fill from other bands; record `actual_per_class`; warn                  |
| Assessment without matching job     | Skip during export; do not count toward pool                            |
| Multiple usernames with assessments | Export aborts with clear error                                          |
| Missing CV in S3 at export          | Abort export                                                            |
| Missing dataset files at run        | Abort runner (non-zero)                                                 |
| `--dataset-version` omitted, >1 dir | Abort with list of available `DDMMYYYY` versions                        |
| Manifest version ≠ directory name   | Abort runner (non-zero)                                                 |
| Single entry agent exception        | Record `error`, `predicted: null`; continue                             |
| >20% entry failures                 | Abort runner (non-zero); still write partial results if any             |
| Score outside [0, 100] from agent   | Should not happen (Pydantic); if validation fails, treat as entry error |
| Re-export same `DDMMYYYY`           | Overwrite that version directory after warning log                      |


---



## Assumptions and risks

**Assumptions**

- Exactly one meaningful username in production assessments today.
- Historical assessments were produced by a prompt/model close enough that
category labels are a useful regression target (they are **not** human
judgments).
- Job `description_raw` and related fields in Mongo are sufficient to rebuild
`JobPosting` for the agent’s `_JOB_FIELDS` set.
- Embedding `profile.json` at export freezes the candidate side; intentional
so profile edits do not silently invalidate gold.

**Risks**

- **Label circularity:** improving agreement with a bad historical model can
look like a win. Mitigated later by reintroducing human signals (`skipped`)
or hand-labeled bands.
- **Category boundary sensitivity:** small score jitter near 50/70 flips the
label; adjacent accuracy partially absorbs this.
- **Cost/latency:** 100 PDF-backed LLM calls are slow and paid; `--limit` and
concurrency controls mitigate iteration pain.
- **Dataset sensitivity:** job text + CV + profile are personal/sensitive; they
  are committed by design for reproducibility — treat the repo as private and
  avoid publishing dataset trees publicly.
- **Stratification drift:** if production scores cluster in `good`, the frozen
  set may still be imbalanced after best-effort fill — always trust
  `manifest.stratification.actual_per_class` when interpreting accuracy.
- **`DDMMYYYY` is not chronologically sortable as a string** (day-first). Do not
  pick “latest” by lexicographic order; require explicit `--dataset-version` when
  multiple versions exist (or resolve by `manifest.exported_at` if a “latest”
  helper is added later).


