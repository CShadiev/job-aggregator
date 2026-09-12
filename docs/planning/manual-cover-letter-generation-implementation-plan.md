# Manual Cover Letter Generation — Implementation Plan

**Status:** Implemented
**Last updated:** 2026-09-12
**Open questions:** 0

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done) · `Implemented` (shipped; sections below describe the code as built).

All three phases landed as designed. Two details worth noting against the plan text: the client-facing status is its own two-value enum (`CoverLetterGenerationStatus` in `models/jobs_api.py`) so `failed` cannot leak into a response, and `ensure_cover_letter_task_indexes` is called only from the API lifespan — the worker never touches `cover_letter_tasks`.

---

## Problem

The LangGraph pair subgraph generates a cover letter only when `cv_ats_match_score >= COVER_LETTER_MIN_CV_SCORE` (default 80) in `orchestration/routing.py:17-29`. Assessed jobs below that gate end successfully with no `job_applications.cover_letter_key`. The jobs API already serves and updates cover letters (`GET`/`PATCH /jobs/{job_uid}/cover-letter` in `api/routes/jobs.py:59-108`) but has no way to *request* generation for a below-threshold job.

Candidates still apply to some of those jobs. Generation is an LLM call (~11s mean), so the request cannot be handled synchronously. This feature adds an authenticated, pollable endpoint that starts generation as a FastAPI background task and tracks status in MongoDB. Push notification of completion is out of scope; the client polls the same endpoint.

## Scope

### In scope

- `POST /jobs/{job_uid}/cover-letter/generate` — start-or-poll cover-letter generation for `(username, job_uid)`.
- MongoDB `cover_letter_tasks` collection with `pending` / `complete` / `failed` document status, unique on `(username, job_uid)`, application-level expiry of 90s on `pending`.
- FastAPI `BackgroundTasks` execution of the existing `CoverLetterGenerationAgent`, writing JSON to object storage and setting `job_applications.cover_letter_key` the same way the pipeline does.
- Shared generation-and-persist helper extracted from `orchestration/nodes/pair.py:127-176` so the pipeline and the API do not diverge.
- Eligibility: a stored fit assessment for the current user; existing `cover_letter_key` short-circuits to `complete` and is the proxy for “pipeline already generated one” (including the score gate).
- Unit tests for eligibility, task reuse, expiry/failed restart, and background completion; no priced LLM calls in the unit suite.

### Out of scope

- Notifying the client when the background task finishes (no websocket, SSE, or webhook).
- Regenerating an existing cover letter (jobs that already have `cover_letter_key`).
- Changing the pipeline score gate (`COVER_LETTER_MIN_CV_SCORE`); automatic generation for high-scoring pairs is unchanged.
- Returning `failed` on the HTTP response — `failed` is an internal document status treated like expiry (Q3).
- Frontend UI / polling loop (separate client repo).
- PDF generation as part of this task (PDF remains on-demand via `GET /{job_uid}/cover-letter-pdf`).

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| Cover-letter HTTP API | `api/routes/jobs.py:59-108` | `GET`/`PATCH /{job_uid}/cover-letter` and `GET /{job_uid}/cover-letter-pdf` stay read/edit of the document. New trigger is `POST .../cover-letter/generate` so POST on `/cover-letter` remains free for a future “write content directly” feature (Q4). CORS already allows `POST` (`main.py:74-78`). |
| Pipeline generation | `orchestration/nodes/pair.py:127-176` | Reads existing key, loads assessment + profile, calls `cover_letter_agent.generate`, writes temp JSON, `upload_coverletter_json`, `update_job_application_status`. Extract the generate-upload-update sequence; keep pair-node control flow (reuse key / missing assessment → `_fail_pair`). |
| Score gate | `orchestration/routing.py:17-29`, `config.py:112` | Pipeline skips cover letter below `COVER_LETTER_MIN_CV_SCORE` (80). Manual request does not re-check the score; absence of `cover_letter_key` is the bypass (Q5). |
| Agent | `agents/cover_letter_generation.py:47-63` | Already records LLM usage/cost. Instantiated today only in `orchestration/deps.py:120` (worker process). The API process must construct one in lifespan (`main.py:35-63`). |
| Assessment lookup | `repository/mongo_jobs_repository.py:442-455` | `get_assessment(username, job_uid)` is the hard eligibility check (Q5). |
| Cover-letter key | `repository/mongo_jobs_repository.py:465-485` | `get_application_cover_letter_key`. If set, return `complete` without scheduling. Application status upsert already handles a missing `job_applications` row (`update_job_application_status` at line 535). |
| Job + profile | `repository/mongo_jobs_repository.py:341-377` | `get_user_profile`, `get_job` — both required by the agent. Validate before scheduling. |
| Object storage | `repository/object_storage.py:60-76` | Same S3 key layout the GET endpoint reads: `job-aggregator/{username}/cover_letters/{job_uid}.json`. |
| Auth | `api/deps.py:19-27` | `AppCurrentUser` is currently hardcoded to `cshadiev`. Task unique key is still `(username, job_uid)` (Q1). |
| Failed pipeline tasks | `models/failed_tasks.py`, `MongoJobsRepository.store_failed_task` | Pipeline-only envelope (`node`, `cycle_id`, `thread_id`). API failures stay on the cover-letter task document (`error` field), not here (Q3). |
| `job_processing` collection | `config.py:71`, `mongo_jobs_repository.py:232-308` | Ingest-queue documents for collectors. Wrong semantic; do not reuse. |
| Background tasks | none in repo | FastAPI `BackgroundTasks` is unused. They run after the response in the API process and die on restart — 90s pending expiry is the recovery mechanism (Q2). API and worker are separate processes (`README.md:192`). |
| Tests | `tests/integration/test_jobs_api.py`, `tests/unit/test_health.py` | OpenAPI / TestClient patterns exist. No HTTP tests currently hit Mongo for jobs routes. |

## Design

### Request flow

Handler for `POST /jobs/{job_uid}/cover-letter/generate`:

1. Authenticated user (`AppCurrentUser`).
2. If no stored fit assessment for `(username, job_uid)` → `404`.
3. If `cover_letter_key` is set → `{ "status": "complete" }` (no task write).
4. Look up the task document for `(username, job_uid)`.
5. If a task exists, status is `pending` or `complete`, and `pending` is not past `expires_at` → return `{ "status": "<that status>" }`. (`failed` never takes this branch.)
6. Otherwise (missing, expired `pending`, or `failed`) claim a new `pending` row (`expires_at = now + 90s`), schedule the background task, return `{ "status": "pending" }`.
7. Background work succeeds → set document `status=complete`, clear `error`. Subsequent polls hit step 5.
8. Background work fails → set `status=failed` with `error`. The next POST takes step 6.

The same endpoint is both the start and the poll. HTTP `status` is only `pending` | `complete`. Client notification on completion is out of scope.

### Data model

Dedicated MongoDB collection `cover_letter_tasks` (`config.MONGODB_COVER_LETTER_TASKS_COLLECTION`), not fields on `job_applications` and not `job_processing`.

```python
class CoverLetterTaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class CoverLetterTask(BaseModel):
    username: str
    job_uid: str
    status: CoverLetterTaskStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    error: str | None = None
```

- Unique index on `(username, job_uid)` (Q1).
- `COVER_LETTER_TASK_TTL_SECONDS: int = 90` (Q2). Applied only when writing `pending`.
- Expiry is **application-checked**, not a Mongo TTL delete. TTL would drop `complete` rows and lose the poll result.
- A row is **claimable** when it is missing, `status=failed` (Q3), or `status=pending` and `expires_at < now`. `complete` is never claimable via the task row; regeneration is out of scope because step 3 already short-circuits on `cover_letter_key`.
- Index created from API lifespan. Today `ensure_pipeline_indexes` runs only in the worker; add `ensure_cover_letter_task_indexes` and call it from `main.py` lifespan (and from the worker ensure path if that helper is the natural place to keep indexes together).

Repository methods:

```python
async def get_cover_letter_task(self, username: str, job_uid: str) -> CoverLetterTask | None: ...
async def claim_pending_cover_letter_task(
    self, username: str, job_uid: str, *, ttl_seconds: int
) -> CoverLetterTask | None:
    """Atomically insert-or-replace a pending row if missing, expired-pending, or failed.
    Returns the claimed pending task, or None if a live pending/complete row won the race.
    """


async def complete_cover_letter_task(self, username: str, job_uid: str) -> None: ...
async def fail_cover_letter_task(self, username: str, job_uid: str, error: str) -> None: ...
```

`claim_pending_cover_letter_task` must be `find_one_and_update` (upsert) filtered to claimable documents so two concurrent POSTs cannot both schedule generation. If the filter does not match (live pending or complete), return `None` and the handler re-reads and returns that status.

### Interfaces

- **Path:** `POST /jobs/{job_uid}/cover-letter/generate` (Q4).
- **Auth:** `AppCurrentUser`.
- **Response 200:** `{ "status": "pending" | "complete" }` — `CoverLetterGenerationStatusResponse`. Never `failed`.
- **404:** no fit assessment for `(username, job_uid)`; or job posting / user profile missing when about to schedule (fail before `BackgroundTasks.add_task`, not after).
- **200 complete:** existing `cover_letter_key`, or a non-expired `complete` task.

`jobs.py` currently never raises `HTTPException`; this endpoint should. CORS already allows POST.

### Shared generation helper

Extract the persist sequence from `cover_letter` in `orchestration/nodes/pair.py:150-171` into `cover_letter_service.py` (next to `auth_service.py` — talks to agent, S3, and Mongo, so it does not belong in `agents/` or `repository/`):

```python
async def generate_and_persist_cover_letter(
    *,
    username: str,
    job: JobPosting,
    assessment: FitAssessment,
    profile: UserProfile,
    agent: CoverLetterGenerationAgent,
    object_storage: ObjectStorage,
    repository: MongoJobsRepository,
) -> str:
    """Generate JSON, upload to S3, set job_applications.cover_letter_key. Returns the object key."""
```

Pair node keeps “reuse existing key / missing assessment → `_fail_pair`” and calls the helper only for generate-upload-update.

Construct `CoverLetterGenerationAgent` in API `lifespan` from `COVER_LETTER_MODEL` (same as `build_deps`) and expose it via `api/deps.py` as `AppCoverLetterAgent`.

### Background task

```python
async def run_cover_letter_generation_task(
    *,
    username: str,
    job_uid: str,
    repository: MongoJobsRepository,
    object_storage: ObjectStorage,
    agent: CoverLetterGenerationAgent,
) -> None:
    try:
        # load job, profile, assessment (validated in the request handler; re-load in case of deletion)
        # generate_and_persist_cover_letter(...)
        # complete_cover_letter_task(...)
    except Exception as exc:
        await repository.fail_cover_letter_task(username, job_uid, error=str(exc))
        log.exception(...)
```

Use FastAPI `BackgroundTasks.add_task` so work starts after the `pending` response is sent. Capture lifespan-scoped clients (repository, storage, agent), not the `Request`. Process restart leaves a `pending` row until `expires_at`; the next POST retakes it.

Do not invoke the LangGraph pair subgraph from the API: that graph needs `cycle_id` / checkpointer / pair state and would couple HTTP latency and worker orchestration.

### Error handling

- **No assessment / missing job / missing profile:** HTTP 404, no task write, no background work.
- **Existing cover_letter_key:** HTTP 200 `{ "status": "complete" }`.
- **Live pending:** HTTP 200 `{ "status": "pending" }`, do not reset `expires_at`.
- **Generation exception:** persist `status=failed`, `error=str(exc)`. Do not write `failed_tasks`. Next POST claims a new pending and retries immediately (no TTL wait). Persistent failures therefore restart on every poll after a failure — accepted. `error` is for ops/debugging on the document.
- **API process crash mid-run:** `pending` until 90s, then claimable.
- **Overlapping generation:** unique index + claim filter. 90s TTL is ~8× mean completion (11s); a call that exceeds 90s can overlap with a retry. Accepted given the measured mean.
- LLM `llm_*` metrics already fire inside the agent; no new metric required.

### Tests

- Handler: no assessment → 404; existing `cover_letter_key` → `complete` without scheduling; missing task → claim pending + schedule; live pending → `pending`, do not reschedule; expired pending → new pending + schedule; `failed` task → new pending + schedule; complete task → `complete`.
- OpenAPI: path `/jobs/{job_uid}/cover-letter/generate` present as POST.
- Race: claim filter prevents two live pending generations (repository test against test Mongo).
- Background completion: mocked agent + storage updates task to `complete` and writes `cover_letter_key`.
- Background failure: mocked agent raise → `failed` with `error`; subsequent claim succeeds.
- Pair node still calls the helper (thin unit test with the helper mocked, or a small extract test).
- No `@pytest.mark.priced` in this suite.

## Open questions

None.

## Decision log

### Q1 — Task unique key is `(username, job_uid)`

**Decided:** 2026-09-12
Unique index and all lookups use `(username, job_uid)`.

**Rejected:** `job_uid` only — cover letters and assessments are per candidate; a second user profile would mix task rows.

**Consequence:** repository methods and the claim filter always take `username`.

### Q2 — Pending-task TTL is 90 seconds

**Decided:** 2026-09-12
`COVER_LETTER_TASK_TTL_SECONDS = 90`. Mean completion is ~11s; 5 minutes was too long for a stuck pending to block retry after an API restart.

**Rejected:** 5-minute default (kickoff leaning) — poor recovery latency relative to observed runtime.

**Consequence:** `expires_at = now + 90s` only when claiming `pending`. A generation that exceeds 90s can overlap a retry; accepted.

### Q3 — Persist `failed` with `error`; treat `failed` as expired

**Decided:** 2026-09-12
On generation exception, set `status=failed` and `error`. The claim filter treats `failed` like an expired pending: the next POST starts a new generation immediately. HTTP responses stay `{ "status": "pending" | "complete" }` — the client never sees `failed`.

**Rejected:** leave the row `pending` until TTL — delays retry after a fast failure. Return `failed` on the poll so the client can stop spinning — rejected in favour of automatic retry on the next poll. Writing `failed_tasks` — that collection is pipeline-shaped (`node`, `cycle_id`, `thread_id`).

**Consequence:** a polling client will restart generation after every failure. `error` is for operators reading the document. Claim filter must include `status=failed`.

### Q4 — `POST /jobs/{job_uid}/cover-letter/generate`

**Decided:** 2026-09-12
Dedicated `/generate` subpath. `GET`/`PATCH /jobs/{job_uid}/cover-letter` remain read/edit of stored content.

**Rejected:** `POST /jobs/{job_uid}/cover-letter` — reads as “write cover-letter content in the body,” which may become a real feature later.

**Consequence:** new route in `api/routes/jobs.py`; CORS already allows POST.

### Q5 — Eligibility is stored assessment plus absence of `cover_letter_key`

**Decided:** 2026-09-12
Require a stored fit assessment (`404` if missing). If `cover_letter_key` is present, return `complete` and do not generate. Do **not** compare `cv_ats_match_score` to `COVER_LETTER_MIN_CV_SCORE`. Absence of the key is the proxy for “pipeline did not generate a letter,” which includes the below-threshold skip and also covers above-threshold pipeline misses.

**Rejected:** extra score-threshold check on the endpoint — duplicates the pipeline gate and would block manual recovery when assess succeeded but cover-letter persist did not. Allowing generation with no assessment — the agent requires a `FitAssessment`.

**Consequence:** handler order is assessment → cover_letter_key → task state. Missing job or profile when scheduling is also `404`.

## Implementation phases

### Phase 1 — Task model + repository

**Depends on:** nothing (Q1–Q3 recorded)
**Reviewable when:** config keys exist; Pydantic model includes `failed`/`error`; unique `(username, job_uid)` index; `get` / `claim_pending` / `complete` / `fail` round-trip against test Mongo; claim is a no-op against live pending and complete.
**Touches:** `config.py`, `models/cover_letter_task.py` (new), `repository/mongo_jobs_repository.py`, index ensure (API lifespan and/or `ensure_pipeline_indexes`), `tests/integration/test_mongo_jobs_repo.py` or a focused new test module

- Add `MONGODB_COVER_LETTER_TASKS_COLLECTION = "cover_letter_tasks"` and `COVER_LETTER_TASK_TTL_SECONDS = 90`.
- Wire `self._cover_letter_tasks` in `MongoJobsRepository`.
- Implement claim as atomic `find_one_and_update` with filter: missing (upsert) **or** `failed` **or** (`pending` and `expires_at < now`).

### Phase 2 — Shared generate-and-persist helper

**Depends on:** nothing from Phase 1
**Reviewable when:** `orchestration/nodes/pair.py` `cover_letter` node calls `generate_and_persist_cover_letter`; generate-upload-update behaviour unchanged.
**Touches:** `cover_letter_service.py` (new), `orchestration/nodes/pair.py`, optional thin unit test

Can proceed in parallel with Phase 1.

### Phase 3 — Endpoint + background task

**Depends on:** Phase 1, Phase 2
**Reviewable when:** `POST /jobs/{job_uid}/cover-letter/generate` matches the request flow; agent is constructed in API lifespan; mocked-agent tests cover the Tests list.
**Touches:** `main.py`, `api/deps.py`, `api/routes/jobs.py`, `models/jobs_api.py` (response model), background-task function (in `cover_letter_service.py` or `api/routes/jobs.py`), `tests/integration/test_jobs_api.py` and/or a new unit module

- Lifespan: build `CoverLetterGenerationAgent`, call index ensure.
- Handler order: assessment 404 → key complete → live pending/complete return → claim + `BackgroundTasks.add_task`.
- Background: helper then `complete_cover_letter_task`; on exception `fail_cover_letter_task`.
