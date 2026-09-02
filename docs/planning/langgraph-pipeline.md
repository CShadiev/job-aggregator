# LangGraph Pipeline Orchestration

## Overview

Replace the Mongo stage-queue orchestration style (as embodied by
`workers/job_processing.py`) with a LangGraph map-reduce pipeline in a **new**
`orchestration/` package. Batch nodes own collect → normalize → dedupe and
persist unique jobs into `jobs`; a fan-out over `(username, job)` pairs runs
screen → conditional fit assessment → conditional cover letter with durable
graph state in MongoDB via `MongoDBSaver`. Intermediate work no longer uses
`job_processing` / `failed_entries`. The legacy worker is left untouched.

## Requirements

**In scope**

- New `orchestration/` module: StateGraph, runner entrypoint, wiring of existing
  `CollectionService`, agents, `MongoJobsRepository`, `ObjectStorage`.
- Batch nodes: collect, normalize, dedupe; side effect after dedupe: insert
  unique postings into `jobs`.
- Map-reduce over `(username, job)` with `Send`: screen → route on
  `worth_full_assessment` → assess → route on `cv_ats_match_score >=` configured
  threshold (default 80) → cover letter.
- Durable LangGraph checkpoints via `langgraph-checkpoint-mongodb`
  (`langgraph_checkpoints` / `langgraph_checkpoint_writes`).
- Long-lived single `thread_id` (config); scheduled re-invokes resume that
  thread and start a new cycle after `END`, clearing batch-scoped channels.
- Persist every screening result to new `screenings` collection.
- Persist node failures to new `failed_tasks` collection (discriminated
  envelope + payload).
- Keep using existing `checkpoints` collection for per-source watermarks
  (unchanged collector / `CollectionService` behavior).
- Config-driven models: screening (default `Model.LUNA_5_6`); deduplication,
  fit assessment, and cover letter (default `Model.GROK_4_3` each).
- Dependencies: add `langgraph`, `langgraph-checkpoint-mongodb`.
- Idempotent pair nodes (skip LLM/S3 work if result already stored) so crash
  resume does not double-bill.
- Unit tests for pure routing / pair-building / finalize helpers.

**Out of scope / non-goals**

- Editing or deleting `workers/job_processing.py`.
- Migrating or dropping existing `job_processing` / `failed_entries` data.
- Removing processing-queue methods from `MongoJobsRepository` (legacy worker
  still needs them).
- Screening confidence thresholds as routing gates.
- Human-in-the-loop, LangGraph Studio deployment, or multi-worker competing
  on the same thread.
- Changing agent prompts / assessment semantics.
- README overhaul beyond a one-line note that a new runner exists (optional
  follow-up).

## Design decisions

### 1. Hybrid graph: batch spine + per-pair map

**Chosen:** One compiled StateGraph. Batch nodes for collect / normalize /
dedupe / persist_jobs / build_pairs / finalize. After `build_pairs`, fan out
with `Send("pair_pipeline", payload)` per `(username, job)`. Pair work is a
**subgraph** with screen → conditional → assess → conditional → cover_letter.

**Rejected:** Entirely per-job end-to-end graph (breaks set-based dedupe).
**Rejected:** LangGraph only for the map half with imperative batch calls
outside (weaker single entrypoint; user chose full graph in a new module).

### 2. Intermediate state in LangGraph; finals in domain collections

**Chosen:** In-flight postings and pair progress live only in graph state +
`MongoDBSaver`. Domain writes:

| When | Collection |
|---|---|
| After successful dedupe | `jobs` (unique postings) |
| After each screen | `screenings` |
| After each assess (keep path) | `assessments` + default `job_applications` row (existing repo behavior) |
| After cover letter | S3 + `job_applications.cover_letter_key` |
| On node failure | `failed_tasks` |
| During collect | `checkpoints` watermarks (existing `CollectionService.collect`) |

**Rejected:** Retaining `job_processing` as a parallel queue.
**Rejected:** Retiring `checkpoints` (source watermarks stay).

### 3. Checkpointer: MongoDBSaver with non-colliding collection names

**Chosen:** `langgraph-checkpoint-mongodb` `MongoDBSaver` with sync
`pymongo.MongoClient` (separate from app `AsyncMongoClient`), collections
`langgraph_checkpoints` and `langgraph_checkpoint_writes` in the same app DB.
Wire via config keys. Graph nodes remain `async`; LangGraph drives the saver.

**Rejected:** Postgres checkpointer (new infra). **Rejected:** custom async
Mongo saver (cost). **Rejected:** default saver collection name `checkpoints`
(collides with source watermarks).

### 4. Map unit = `(username, job)`

**Chosen:** Cartesian product of unique postings × `get_user_profiles()` after
dedupe. Flat `Send` list. Screening and assessment are inherently per-user
(CV / profile).

**Rejected:** Fan-out per job with nested user loops inside one node.

### 5. Screening persistence

**Chosen:** Always write to `screenings` before routing, including drops.
Fields: `username`, `job_uid`, `worth_full_assessment`, `confidence`,
`screened_at`, `model` (string id used for the call).

**Rejected:** Ephemeral routing only. **Rejected:** stuffing drops into
`assessments`.

### 6. Cover letter on the same pair branch

**Chosen:** Conditional edge after assess: if
`cv_ats_match_score >= COVER_LETTER_MIN_CV_SCORE` (default 80) → cover letter
node; else → pair end. Same gate as today’s feed filter, but using the
assessment just produced (no second feed query).

**Rejected:** Separate post-batch cover-letter stage.

### 7. Long-lived thread + cycle-local batch channels

**Chosen:** Fixed `PIPELINE_THREAD_ID` (default `"job-pipeline"`). Runner
sleep-loop calls `ainvoke` with that thread id. After a cycle reaches `END`,
the next invoke starts a new cycle on the same thread; a `finalize` node
**clears** batch-scoped channels (`collected`, `normalized`, `unique_jobs`,
`pairs`, `pair_results`, etc.) so checkpointed state does not grow without
bound. Each cycle assigns a fresh `cycle_id` (UUID) for correlating
`failed_tasks`.

**Rejected:** New `thread_id` per schedule (user chose long-lived).
**Rejected:** Leaving full posting lists in state across cycles.

### 8. Idempotent pair nodes for resume

**Chosen:** Before LLM/S3 work:

- Screen: if `screenings` has `(username, job_uid)`, reuse and route.
- Assess: if `assessments` has `(username, job_uid)`, reuse scores for cover
  routing; do not re-insert.
- Cover letter: if application has `cover_letter_key`, skip.

Needed because mid-map crash + long-lived thread replay must not re-call paid
models for completed pairs.

### 9. New module; legacy worker untouched

**Chosen:** Implement under `orchestration/`; entrypoint
`python -m orchestration.runner` (also register console script). Do not modify
`workers/job_processing.py`. Repo keeps processing/failed_entries APIs for the
legacy path; new code paths never call them.

### 10. Concurrency

**Chosen:** Pass `config={"max_concurrency": PIPELINE_PAIR_CONCURRENCY}`
(default 10) on `ainvoke` so LangGraph limits parallel `Send` tasks. Pair
subgraph does one pair at a time per task (no inner unbounded gather). Batch
normalize keeps existing `DeduplicationAgent` internal batching/`gather`.

**Rejected:** Replicating the current worker bug (semaphore around the whole
task group once).

### 11. Screening model config

**Chosen:** Config-driven model ids resolved via `Model(config.*)` →
`ModelFactory.get_model`:

- `DEDUPLICATION_MODEL` default `Model.GROK_4_3.value` (`grok-4.3`)
- `SCREENING_MODEL` default `Model.LUNA_5_6.value` (`gpt-5.6-luna`)
- `FIT_ASSESSMENT_MODEL` default `Model.GROK_4_3.value` (`grok-4.3`)
- `COVER_LETTER_MODEL` default `Model.GROK_4_3.value` (`grok-4.3`)

## Resolved open questions

| # | Topic | Resolution |
|---|---|---|
| 1 | Map unit | `(username, job)` via `Send` |
| 2 | Durability | LangGraph checkpointer primary for intermediate state |
| 3 | Job lifecycle / multi-user | All pairs for the cycle are mapped; job written to `jobs` once after dedupe; no processing-queue dequeue |
| 4 | Screening persistence | New `screenings` collection, always write |
| 5 | Cover letters | Same pair branch, score gate |
| 6 | Code location | New `orchestration/`; do not touch legacy worker |
| 7 | Models | All pipeline agents config-driven; screening `LUNA_5_6`, others `GROK_4_3` |
| 8 | Source watermarks | Keep `checkpoints` collection as-is |
| 9 | LG checkpointer | `MongoDBSaver`, collections `langgraph_checkpoints` / `langgraph_checkpoint_writes` |
| 10 | Screening store shape | Dedicated `screenings` |
| 11 | Failures | Collection `failed_tasks`, single discriminated envelope |
| 12 | Thread identity | Single long-lived `PIPELINE_THREAD_ID` |
| 13 | Retire semantics | New module simply does not use `job_processing` / `failed_entries`; no drop/migration scripts |

## Interfaces / contracts

### Package layout

```
orchestration/
  __init__.py
  __main__.py          # delegates to runner.main
  runner.py            # sleep loop, ainvoke
  graph.py             # build_pipeline_graph() -> compiled CompiledStateGraph
  state.py             # PipelineState, PairState TypedDicts / reducers
  deps.py              # PipelineDeps dataclass (services, agents, repos)
  nodes/
    __init__.py
    batch.py           # collect, normalize, dedupe, persist_jobs, build_pairs, finalize
    pair.py            # screen, assess, cover_letter, routing callables
  routing.py           # pure functions: route_after_screen, route_after_assess
models/
  failed_tasks.py      # FailedTask envelope + payload helpers
  # screening.py already has ScreeningResult — add ScreeningRecord if useful
```

### Config additions (`config.py`)

```python
DEDUPLICATION_MODEL: str = "grok-4.3"
SCREENING_MODEL: str = "gpt-5.6-luna"
FIT_ASSESSMENT_MODEL: str = "grok-4.3"
COVER_LETTER_MODEL: str = "grok-4.3"
COVER_LETTER_MIN_CV_SCORE: float = 80
PIPELINE_PAIR_CONCURRENCY: int = 10
PIPELINE_THREAD_ID: str = "job-pipeline"
PIPELINE_SCHEDULE_SECONDS: int = 60 * 60 * 12
MONGODB_SCREENINGS_COLLECTION: str = "screenings"
MONGODB_FAILED_TASKS_COLLECTION: str = "failed_tasks"
MONGODB_LANGGRAPH_CHECKPOINT_COLLECTION: str = "langgraph_checkpoints"
MONGODB_LANGGRAPH_WRITES_COLLECTION: str = "langgraph_checkpoint_writes"
```

Leave existing `MONGODB_PROCESSING_COLLECTION` / `MONGODB_FAILED_COLLECTION`
keys for the legacy worker.

### Graph state (illustrative)

```python
# orchestration/state.py
class PipelineState(TypedDict, total=False):
    cycle_id: str
    collected: list[dict]  # JobPosting dumps
    normalize_failed: list[dict]
    unique_jobs: list[dict]
    pairs: list[dict]  # {username, job_uid} (+ optional job dump)
    pair_results: Annotated[list[dict], operator.add]
    # cleared in finalize


class PairState(TypedDict, total=False):
    cycle_id: str
    username: str
    job: dict  # JobPosting dump
    screening: dict  # ScreeningResult dump
    assessment: dict | None  # FitAssessment dump
    cover_letter_key: str | None
    skipped_reason: str | None
```

Serialize with `model_dump(mode="json")` at node boundaries so the checkpointer
never sees raw Pydantic models or CV bytes.

### Dependencies object

```python
@dataclass
class PipelineDeps:
    collection_service: CollectionService
    repository: MongoJobsRepository  # or narrow protocol
    object_storage: ObjectStorage
    screening_agent: ScreeningAgent
    fit_assessment_agent: FitAssessmentAgent
    cover_letter_agent: CoverLetterGenerationAgent
    cover_letter_min_cv_score: float
```

Inject into nodes via closure when building the graph (or LangGraph
context/deps pattern consistent with installed langgraph version). Prefer
closures in `graph.py` to avoid inventing a new DI framework.

### Repository methods to add

On `MongoJobsRepository` (used by new module; safe additions):

```python
async def store_screening(
    self,
    *,
    username: str,
    job_uid: str,
    result: ScreeningResult,
    model: str,
) -> None: ...


async def get_screening(
    self,
    username: str,
    job_uid: str,
) -> ScreeningResult | None: ...


async def get_assessment(
    self,
    username: str,
    job_uid: str,
) -> FitAssessment | None: ...


async def store_failed_task(self, task: FailedTask) -> None: ...


async def get_application_cover_letter_key(
    self,
    username: str,
    job_uid: str,
) -> str | None: ...
```

Reuse existing: `get_checkpoint` / `set_checkpoint` (via `CollectionService`),
`get_existing_uids`, `get_recent_normalized_keys`, `store_processed_jobs` (or
rename-equivalent upsert — see edge cases), `store_assessment`,
`update_job_application_status`, `get_user_profiles`.

**Do not call** from orchestration: `store_in_processing`,
`get_normalization_feed`, `get_deduplication_feed`, `get_assessment_feed`,
`save_normalized_results`, `mark_ready_for_assessment`,
`remove_from_processing`, `store_failed`.

### `FailedTask` model

```python
# models/failed_tasks.py
NodeName = Literal[
    "collect",
    "normalize",
    "dedupe",
    "persist_jobs",
    "screen",
    "assess",
    "cover_letter",
]


class FailedTask(BaseModel):
    node: NodeName
    thread_id: str
    cycle_id: str
    task_id: str | None = None
    error: str
    failed_at: datetime
    retryable: bool = False
    payload: dict[str, Any]  # node-specific: uid, username, raw entry, etc.
```

### Routing (pure)

```python
def route_after_screen(state: PairState) -> Literal["assess", "pair_end"]: ...


def route_after_assess(
    state: PairState,
    *,
    min_cv_score: float,
) -> Literal["cover_letter", "pair_end"]: ...
```

### Graph topology

```text
START
  → collect
  → normalize          # no-op pass-through if collected empty
  → dedupe
  → persist_jobs       # write unique_jobs → jobs; no-op if empty
  → build_pairs        # profiles × unique_jobs; if no pairs → finalize
  → fanout             # returns list[Send("pair_pipeline", ...)]
  → pair_pipeline      # subgraph: screen → (assess?) → (cover_letter?)
  → finalize           # clear batch channels; log cycle summary
  → END
```

`pair_pipeline` subgraph:

```text
START → screen → route_after_screen
                    ├─ assess → route_after_assess
                    │              ├─ cover_letter → END
                    │              └─ END
                    └─ END
```

Parent uses a reducer on `pair_results` so each subgraph completion appends a
summary dict (`username`, `job_uid`, `worth_full_assessment`, scores if any,
`cover_letter_key`, `error` if any).

### Runner

```python
# orchestration/runner.py
async def run_once(graph, deps, checkpointer_client) -> None:
    config = {
        "configurable": {"thread_id": Config.PIPELINE_THREAD_ID},
        "max_concurrency": Config.PIPELINE_PAIR_CONCURRENCY,
    }
    await graph.ainvoke({"cycle_id": str(uuid4())}, config=config)

def main() -> None:
    # build deps, sync MongoClient for MongoDBSaver, compile graph, loop:
    #   asyncio.run(run_once(...)); time.sleep(PIPELINE_SCHEDULE_SECONDS)
```

### Dependencies (`pyproject.toml`)

Add:

- `langgraph` (current stable compatible with Python ≥3.13)
- `langgraph-checkpoint-mongodb`

Keep `pymongo` for both async app client and sync checkpointer client.

## Implementation plan

1. **Deps & config** — Add packages to `pyproject.toml` / `uv lock`. Extend
   `Config` with keys listed above. Do not remove legacy collection settings.

2. **Models** — Add `models/failed_tasks.py`. Optionally add
   `ScreeningRecord` in `models/screening.py` for the Mongo document shape
   (or keep as plain dict in repo method).

3. **Repository** — Add screening / failed_task / get_assessment /
   cover_letter_key helpers on `MongoJobsRepository`. Prefer upsert or
   duplicate-safe insert for `store_screening` / assessments under resume
   (unique index on `(username, job_uid)` for `screenings` and ensure
   assessments lookup-before-insert). Add indexes in a short comment or
   ensure-on-startup helper used only by the new runner.

4. **`orchestration/state.py` + `routing.py`** — Define state types and pure
   routers; unit-test routers and “build pairs” / “finalize clear” helpers
   without LLM.

5. **`orchestration/deps.py`** — Construct collectors (same set as legacy
   worker: LinkedIn DE/PL/UK + Arbeitnow), `CollectionService`, agents with
   configured models, `ObjectStorage`, repository.

6. **Batch nodes** (`nodes/batch.py`):
   - `collect`: `collection_service.collect()`; store invalids as
     `failed_tasks` (`node="collect"`); set `collected` from postings;
     ensure `cycle_id` present.
   - `normalize`: `collection_service.normalize(collected)`; write normalize
     failures to `failed_tasks`; set state to processed list.
   - `dedupe`: `collection_service.deduplicate(...)`; set `unique_jobs`.
   - `persist_jobs`: `store_processed_jobs(unique_jobs)` (see edge case:
     upsert).
   - `build_pairs`: load profiles; emit `pairs`; if empty, path to finalize.
   - `finalize`: log counts from `pair_results`; return cleared batch fields.

7. **Pair subgraph** (`nodes/pair.py` + `graph.py`):
   - `screen`: idempotent read; else load CV bytes from ObjectStorage, call
     `ScreeningAgent.screen`, `store_screening`, set `screening` on state.
   - On exception: `store_failed_task(node="screen", ...)`, set
     `skipped_reason`, end pair (do not fail whole graph).
   - `assess` / `cover_letter`: same pattern; cover letter reuse logic from
     `_generate_cover_letter_task` in the legacy worker (tmp file → S3 →
     `update_job_application_status`) without importing from
     `workers/job_processing.py` — copy the small helper into
     `orchestration/nodes/pair.py` or a shared private util under
     `orchestration/`.

8. **`graph.py`** — Wire nodes, conditional edges, `Send` fan-out from
   `build_pairs` (or dedicated `fanout` node). Compile with `MongoDBSaver`.
   Export `build_graph(deps) -> CompiledStateGraph`.

9. **`runner.py` / `__main__.py`** — Schedule loop; structured logging
   (`event=...`) consistent with legacy worker; console script
   `run-pipeline` optional in `[project.scripts]`.

10. **Tests** — `tests/unit/test_pipeline_routing.py` (screen/assess routes,
    empty collect → no pairs, finalize clears keys). Optionally
    `tests/unit/test_pipeline_pairs.py` for pair list construction.
    No priced LLM tests in unit suite.

11. **Manual smoke** — Run `python -m orchestration.runner` once against
    dev Mongo with collectors configured; confirm watermarks advance, jobs
    inserted, screenings/assessments written, LG checkpoint collections
    created, legacy worker still runnable.

## Edge cases and error handling

| Case | Behavior |
|---|---|
| Empty collect | Normalize/dedupe/persist no-op; `build_pairs` yields no `Send`; finalize → END |
| Normalize partial failure | Failed postings → `failed_tasks`; successful continue to dedupe |
| All postings deduped away | No `jobs` writes; no pairs; finalize |
| `jobs` insert when uid already exists | Use upsert / ordered=False ignore duplicates so re-processing a watermark overlap does not crash the cycle |
| No user profiles | No pairs; jobs still persisted after dedupe |
| Screening says drop | Persist screening; skip assess & cover letter |
| Screening/assess/cover throws | Record `failed_tasks` for that pair/node; continue other pairs (`retryable=False` by default for LLM errors unless clearly transient) |
| Process crash mid-map | Re-invoke same `thread_id`; idempotent pair nodes skip completed work; unfinished pairs run |
| Cover letter score below threshold | Skip cover letter; pair ends successfully |
| CV missing in S3 | Failed task on screen (and assess if somehow reached); skip pair |
| Duplicate `(username, job_uid)` screening insert on race | Unique index + catch duplicate key; treat as idempotent success |
| Long-lived state growth | `finalize` must null/empty all batch list channels every cycle |
| Concurrent second runner same thread | **Unsupported** — document single-runner assumption |

## Assumptions and risks

- **Assumption:** Official `MongoDBSaver` works with async `ainvoke` on the
  target langgraph version when constructed with a sync `MongoClient`. If the
  installed version blocks the event loop unacceptably, wrap is a follow-up;
  do not block the first implementation on a custom async saver.
- **Assumption:** Re-invoking a completed graph with the same `thread_id`
  starts a new cycle that merges input (`cycle_id`) with prior checkpoint;
  `finalize` clearing is sufficient to avoid replaying old `Send` targets.
  Verify against installed langgraph docs during implementation; if input
  merge is sticky, explicitly overwrite list channels in the collect node at
  cycle start.
- **Assumption:** Single active runner for `PIPELINE_THREAD_ID`.
- **Risk:** Checkpoint document size if pair payloads embed full job
  descriptions × many users — mitigate by storing `job_uid` in `Send` payload
  and resolving the posting from parent `unique_jobs` only if the installed
  API allows; otherwise accept dumps for v1 and monitor.
- **Risk:** `store_processed_jobs` today is insert_many — must become
  duplicate-safe in the repo method used by orchestration (change
  implementation carefully so legacy worker behavior stays acceptable, or add
  `upsert_jobs` and call that from orchestration only).
- **Risk:** CollectionService currently advances watermarks inside `collect`
  when any postings return — same as today; orchestration inherits that
  timing (watermark can advance even if later normalize fails for some
  items). Accept parity with legacy; do not redesign watermark timing here.
