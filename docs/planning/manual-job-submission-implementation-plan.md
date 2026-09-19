# Manual Job Submission — Implementation Plan

**Status:** Implemented
**Last updated:** 2026-09-19
**Open questions:** 0

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done) · `Implemented` (shipped; sections below describe the code as built).

All three phases landed as designed. `POST /jobs/submit` is start-and-poll; `job_uid` is a client uuid4; background work lives in `job_submit_service.py`.

---

## Problem

The product can evaluate a job against a candidate only after the scheduled LangGraph pipeline has collected that posting from a scraper. There is no HTTP path for a candidate to hand in a job they found themselves.

That gap shows up in two places:

- The jobs API can search assessed jobs, update application status, and start cover-letter generation (`api/routes/jobs.py`), but every one of those routes assumes a `job_uid` that already exists in Mongo.
- The pair subgraph (`orchestration/nodes/pair.py`) will screen, assess, and maybe draft a letter — but only for pairs the batch spine built from collected postings.

A candidate who pastes a structured description therefore cannot get a fit assessment or a cover letter for that role. This feature adds an authenticated accept-and-poll endpoint that accepts that description, runs normalisation / persist / assess / cover-letter in the API process, and stores the results so the existing feed and cover-letter routes can serve them.

The closest shipped analogue is `POST /jobs/{job_uid}/cover-letter/generate` ([manual-cover-letter-generation-implementation-plan.md](manual-cover-letter-generation-implementation-plan.md)). That endpoint starts generation for a job that is *already* assessed. This feature starts further upstream: there is no job yet. The client supplies a uuid4 `job_uid` (Q3), so start and poll are the same `POST /jobs/submit` — the same pattern as cover-letter generate, with the uid in the body instead of the path.

## Scope

### In scope

- `POST /jobs/submit` — authenticated start-or-poll of evaluate-this-JD for the current user (Q1, Q9, Q10).
- Request carries a client-generated uuid4 `job_uid` plus the structured JD (Q2, Q3). Response is `{ "job_uid", "status": "pending" | "complete" }` (Q8).
- Title and company normalisation via `DeduplicationAgent`.
- Persist as a `JobPosting` with `source="manual"` and `uid` equal to the client uuid; do **not** embed into the OpenSearch `jobs` corpus (Q3, Q6).
- Fit assessment for `(current user, job)` via `FitAssessmentAgent` + `store_assessment` (skips screening; Q4).
- Cover letter via `generate_and_persist_cover_letter`, ignoring `COVER_LETTER_MIN_CV_SCORE` (Q4).
- Task document for the background run, unique on `(username, job_uid)`. Repeating the POST with the same `job_uid` is the poll (Q7). A new uuid is a new job; duplicate-JD detection is out of scope (Q5).
- Tests with mocked LLM agents; no `@pytest.mark.priced` in this suite.

### Out of scope

- Parsing an unstructured JD (HTML paste, PDF, LinkedIn URL scrape). Input is already structured.
- Server-side uid minting, slugification, or timestamp composition (Q3 reversed).
- Deduplicating a submitted JD against scraped jobs or against the user’s previous submits (Q5).
- Indexing submitted jobs into OpenSearch `jobs`, and any pipeline change so other users are paired with them (Q6).
- Changing the scheduled pipeline, its screening gate, or `COVER_LETTER_MIN_CV_SCORE` for *collected* jobs.
- Regenerating an existing cover letter for a uid that already has `cover_letter_key`.
- Frontend UI for the submit form (separate client repo).
- CV upload / profile write (still no write path; see grounding).
- Invoking the LangGraph pair subgraph from the API process (same rejection as the cover-letter plan: the graph needs `cycle_id` / checkpointer / pair state).

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| Cover-letter start-or-poll | `api/routes/jobs.py:124-179` | The pattern to copy: eligibility checks, reportable live pending/complete, claim, `BackgroundTasks.add_task`, `{ status: pending \| complete }`. Submit puts `job_uid` in the body instead of the path because the job does not exist yet. |
| Jobs HTTP API | `api/routes/jobs.py` | Other mutating routes take a path `job_uid` that already exists. `POST /jobs/submit` is the create. CORS already allows POST (`main.py:82`). |
| Canonical posting | `models/collection_service.py:17-67` | `JobPosting` requires `uid`, `source`, `title`, `company`, `location`, `remote`, `url`, `description_raw`, `posted_at`, `collected_at`. Request is a dedicated model; `uid` is the client uuid, `source` is `"manual"`, timestamps and `*_normalized` are server-filled (Q2, Q3). |
| Collector UID convention | `collection_service/arbeitnow_collector.py:127`, `indeed_apify_parser.py:50`, `linkedin_apify_parser.py:30` | Scraped uids are `{source}:{id}` (contain a colon). A uuid4 is hyphenated hex with no colon, so it cannot collide with a scraped uid. That is why the request field is typed UUID4 rather than free-form `str` — a client sending `linkedin:abc` would `upsert_jobs` over a corpus row. |
| Title/company normalisation | `agents/deduplication.py:35-60`, `collection_service/collection_service.py:82-100` | LLM batch API, even for one posting. Failures become `FailedJobPosting`. Pipeline writes `failed_tasks` and drops the posting; this flow fails the task document instead (cover-letter plan Q3 pattern). Agent is constructed today only in `orchestration/deps.py:112`. |
| Dedup against the corpus | `collection_service/collection_service.py:102-153` | Not called. Always insert (Q5). |
| Persist jobs | `repository/mongo_jobs_repository.py:418-430` | `upsert_jobs` by `uid`. Shared `jobs` collection. Privacy is “do not embed + assessment is per-user,” not a separate collection (Q6). |
| Job embeddings | `orchestration/nodes/batch.py:161-193` | Pipeline indexes unique jobs into OpenSearch `jobs` after persist. Submitted jobs skip this. `build_pairs` only retrieves uids from the current collect batch anyway, so a Mongo-only row is already invisible to other users’ cycles. |
| Screening gate | `orchestration/routing.py:8-14` | Skipped. Always assess, always generate a letter (Q4). |
| Fit assessment | `agents/fit_assessment.py:54-62`, `orchestration/nodes/pair.py:93-121` | Needs `UserProfile` + `cv_text` + `JobPosting`. CV text from `ensure_cv_text` (`cv_text_service.py:11`). API lifespan must gain `FitAssessmentAgent` and `CVTextExtractionAgent`. |
| Assessment persist | `repository/mongo_jobs_repository.py:130-164` | `insert_one` of a denormalized doc plus OpenSearch `assessments` when `job` is passed — that is how the submitter’s `POST /jobs/search` feed sees the posting. Index on `(username, job_uid)` is **not unique**. Background retry must `get_assessment` first (Q7), matching the pair node (`orchestration/nodes/pair.py:98-102`). |
| Cover letter | `cover_letter_service.py:18-53` | Reuse `generate_and_persist_cover_letter`. Do not call `POST .../cover-letter/generate` from this flow (it 404s until an assessment exists). Score gate is bypassed (Q4). Background retry short-circuits on existing `cover_letter_key`. |
| Cover-letter tasks | `models/cover_letter_task.py`, `config.py:82,118` | Wrong semantic — letter generation for an already-assessed job. Submit gets its own collection and TTL (three LLM calls; 180s, see Q1). |
| Auth / current user | `api/deps.py:21-29` | `AppCurrentUser`. Assessment and cover letter are always for `user.username`. |
| Profile / CV | `api/routes/users.py`, `repository/object_storage.py:138-148` | No CV upload route. Missing profile or missing S3 CV is HTTP 404 before claiming a task or scheduling work. |
| API lifespan | `main.py:36-70` | Today: Mongo, Auth0, SearchService, repository, ObjectStorage, `CoverLetterGenerationAgent`. Add `DeduplicationAgent`, `FitAssessmentAgent`, `CVTextExtractionAgent`. No `EmbeddingClient`. |
| Tests | `tests/unit/test_manual_cover_letter_generation.py` | TestClient + dependency overrides + mocked repository/agent. OpenAPI assertions in `tests/integration/test_jobs_api.py`. |

## Design

### Request flow

Handler for `POST /jobs/submit` (start **and** poll), modelled on `generate_job_cover_letter`:

1. Authenticated user (`AppCurrentUser`).
2. Validate `ManualJobSubmitRequest` (Q2). `job_uid` must be UUID4 — 422 otherwise.
3. If a stored task for `(username, job_uid)` is live `pending` or `complete` → return `{ job_uid, status }` (do not reset `expires_at` on live pending).
4. If `get_assessment` and `get_application_cover_letter_key` are both set → `{ job_uid, "complete" }` (no task write). Covers a completed run whose task row was lost.
5. 404 if no user profile or if the CV cannot be loaded — fail before claiming. No LLM calls.
6. Claim a pending `manual_job_tasks` row (`expires_at = now + 180s`). If the claim loses the race, re-read and return that status (or `pending`).
7. `BackgroundTasks.add_task` the service run. Return `{ job_uid, "pending" }`.

Repeating the POST with the **same** `job_uid` is the poll. Repeating it with a **new** uuid is a new job. Other body fields are ignored when step 3 or 4 short-circuits; they are used to build the `JobPosting` only when work is scheduled or retried.

`failed` never appears on the wire. A `failed` or expired-`pending` task is claimable: this POST takes step 6 and retries. Same recovery as cover-letter generate (that plan’s Q3).

Background work (`job_submit_service.py`, next to `cover_letter_service.py`):

1. Build `JobPosting` (`source="manual"`, `uid=str(job_uid)`, `collected_at=now`, `posted_at` from request or now, client fields copied).
2. `DeduplicationAgent.normalize([posting])`. If the posting is in `failed`, fail the task; do not `upsert_jobs`.
3. `upsert_jobs([posting])`. No corpus dedup (Q5). No OpenSearch `jobs` embed (Q6).
4. Reuse `get_assessment(username, job_uid)` if present; otherwise `ensure_cv_text` → `FitAssessmentAgent.assess` → `store_assessment(..., job=job)` (Q7).
5. Reuse `get_application_cover_letter_key` if set; otherwise `generate_and_persist_cover_letter` (Q4, Q7).
6. `complete_manual_job_task`. On any exception, `fail_manual_job_task` with `error=str(exc)` and log. Never raise out of the background function.

Do not call `build_pipeline_graph` / `pair_pipeline`. Do not write `failed_tasks`.

### Data model

Domain rows use existing collections: `jobs`, `assessments` (and OpenSearch `assessments` via `store_assessment`), `job_applications`, S3 cover-letter JSON at `job-aggregator/{username}/cover_letters/{job_uid}.json`.

New collection `manual_job_tasks` (`config.MONGODB_MANUAL_JOB_TASKS_COLLECTION`), same shape as `CoverLetterTask`:

```python
class ManualJobTaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class ManualJobTask(BaseModel):
    username: str
    job_uid: str
    status: ManualJobTaskStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    error: str | None = None
```

- Unique index on `(username, job_uid)`.
- `MANUAL_JOB_TASK_TTL_SECONDS = 180`. Applied only when writing `pending`. Three sequential LLM calls; 90s (cover-letter TTL) is too tight, 5 minutes is slow recovery after an API restart. 180s is ~6× a 30s run.
- Expiry is application-checked, not a Mongo TTL delete (would drop `complete` rows and lose the poll result).
- Claimable when missing, `failed`, or `pending` and `expires_at < now`. `complete` is never claimable.
- Index created from API lifespan (`ensure_manual_job_task_indexes`).

Repository methods mirror cover-letter tasks: `get_manual_job_task`, `claim_pending_manual_job_task`, `complete_manual_job_task`, `fail_manual_job_task`. Claim is `find_one_and_update` (upsert) filtered to claimable documents.

`JobPosting` server fields:

- `source = "manual"`
- `uid` = canonical hyphenated uuid4 string from the request (`str(UUID)`)
- `posted_at` = request value if provided, else `now(UTC)`
- `collected_at` / `updated_at` = `now(UTC)`
- `title_normalized` / `company_normalized` = agent output, never client-supplied

No `manual:` prefix on the uid. Origin lives on `source`. UUID4’s hyphenated-hex shape cannot match `{source}:{id}`.

### Interfaces

- **Path:** `POST /jobs/submit` — start and poll (Q9, Q10). Auth: `AppCurrentUser`.
- **Body:** `ManualJobSubmitRequest` (Q2):

  | Field | Required | Notes |
  | --- | --- | --- |
  | `job_uid` | yes | UUID4. Stored as `str` on `JobPosting.uid`. |
  | `title` | yes | |
  | `company` | yes | |
  | `description_raw` | yes | |
  | `url` | yes | not unique |
  | `location` | no | default `""` |
  | `remote` | no | default `false` |
  | `tags` | no | default `[]` |
  | `job_types` | no | default `[]` |
  | `posted_at` | no | default now, UTC-normalised via `ts_validator` |

- **200:** `ManualJobSubmitResponse`: `{ "job_uid": str, "status": "pending" | "complete" }`. Reuse `CoverLetterGenerationStatus` (same two values, `failed` never on the wire) or an alias so the client sees one status vocabulary.
- **404:** missing profile or CV, and only when about to schedule (not on a live pending/complete short-circuit).
- **422:** request schema, including non-UUID4 `job_uid`.
- Agent failures: task → `failed` + `error`; next POST retries; HTTP stays `pending`.

Once `complete`, the client uses existing `POST /jobs/search`, `GET /jobs/{job_uid}/cover-letter`, and `GET /jobs/{job_uid}/cover-letter-pdf`. `POST /jobs/{job_uid}/cover-letter/generate` also works as a letter-only retry if this flow stored an assessment but not a letter — but the submit poll itself retries the whole background run, which short-circuits to the existing assessment and key.

### Error handling

- **Invalid `job_uid`:** HTTP 422, no task.
- **No profile / no CV:** HTTP 404, no task, no background work (unless already live pending/complete).
- **Live pending:** HTTP 200 `pending`, do not reset `expires_at`.
- **Complete task, or assessment + `cover_letter_key`:** HTTP 200 `complete`.
- **Normalise fails:** no `upsert_jobs`, task `failed`. Next POST retries with the same uid and body.
- **Assess fails after persist:** job row exists. Next POST retries; `get_assessment` prevents a duplicate insert if the write actually landed.
- **Cover letter fails after assess:** job is already on the feed. Next POST retries; `get_assessment` + existing `cover_letter_key` check skip completed steps. Operators can also hit `POST .../cover-letter/generate`.
- **API process crash mid-run:** `pending` until 180s, then claimable.
- **Overlapping runs for one uid:** unique index + claim filter. 180s TTL vs a call that exceeds it can overlap; accepted, same as cover-letter generate.
- **New uuid on a new POST:** new task, new LLM calls. Not an error.
- **Two users, same uuid4:** astronomically unlikely; `upsert_jobs` would share a `jobs` row. Assessments stay per `(username, job_uid)`. Not worth extra scheme.

### Observability

LLM `llm_*` metrics already fire inside each agent. Structured logs bind `event` (e.g. `manual_job_submit_request`, `manual_job_submit_task_error`), `username`, and `job_uid`. No new metric.

### Tests

Copy `tests/unit/test_manual_cover_letter_generation.py` (TestClient, dependency overrides, mocked agents/repository). No `@pytest.mark.priced`.

Handler (`POST /jobs/submit`):

- 422 on missing `title` / `company` / `description_raw` / `url` / `job_uid`.
- 422 on `job_uid` that is not UUID4 (including a collector-shaped `linkedin:abc`).
- 404 when profile is missing; no claim, no background.
- 404 when CV load fails; no claim, no background.
- Missing task → claim pending + schedule, 200 `{job_uid, pending}`.
- Live pending → `pending`, do not reschedule.
- Complete task → `complete`, do not reschedule.
- Assessment + `cover_letter_key` without a task row → `complete`.
- Expired pending → new pending + schedule.
- Failed task → new pending + schedule.
- Two POSTs with different uuid4s both schedule (two jobs).

Background (mocked agents):

- Normalise failure → no `upsert_jobs`, no `store_assessment`, task `failed`.
- Happy path → `upsert_jobs` with `source="manual"`, `uid` equal to the request uuid string, normalised fields set, `store_assessment` called with the posting, cover-letter helper called, task `complete`. SearchService job-corpus index **not** called.
- Existing assessment for that uid → assess agent not called; letter still generated if no key.
- Existing `cover_letter_key` → letter agent not called; task `complete`.
- Agent raise → task `failed` with `error`; subsequent claim succeeds.

OpenAPI: path `/jobs/submit` present as POST; request schema includes `job_uid`.

## Open questions

None.

## Decision log

### Q1 — Accept-and-poll with a dedicated task row

**Decided:** 2026-09-19
`POST /jobs/submit` validates, claims a `manual_job_tasks` pending row, schedules FastAPI `BackgroundTasks`, and returns `{ job_uid, status: pending }`. The same POST is the poll (Q3, Q10). Work is normalise + persist + assess + cover letter. `MANUAL_JOB_TASK_TTL_SECONDS = 180`. Capture lifespan-scoped clients, not the `Request`. Do not invoke LangGraph from the API.

**Rejected:** synchronous handler — three LLM calls will blow reverse-proxy timeouts; cover-letter generate already established that LLM work is not request-scoped. Reusing `cover_letter_tasks` — that collection means “letter for an already-assessed job.” Hybrid “persist the job synchronously, assess in the background” — the client already has the uid.

**Consequence:** a task model + repository claim/complete/fail, API lifespan agents. Process restart leaves `pending` until `expires_at`.

### Q2 — Dedicated `ManualJobSubmitRequest`

**Decided:** 2026-09-19 (revised same day to include `job_uid`)
Required: `job_uid` (UUID4), `title`, `company`, `description_raw`, `url`. Optional: `location` (default `""`), `remote` (default `false`), `tags` / `job_types` (default `[]`), `posted_at` (default now, UTC-normalised). Not a `JobPosting`; clients never send `source` or `*_normalized`.

**Rejected:** accept `JobPosting` — would let the client set `source` / normalised fields, or require “send these fields we ignore.” Optional `url` — the model still needs a URL (`JobPosting.url` is required); a careers-page URL is fine. Free-form string `job_uid` — would allow overwriting a scraped `{source}:{id}` via `upsert_jobs`.

**Consequence:** request model lives in `models/jobs_api.py`. 422 on missing required fields or non-UUID4 `job_uid`.

### Q3 — Client-generated uuid4 is the job uid; `source="manual"`

**Decided:** 2026-09-19 (revised same day; first decision was server-minted `manual:{company}-{title}-{timestamp}`)
The client generates a uuid4 and sends it as `job_uid`. `JobPosting.uid` is the canonical hyphenated string; `source` is `"manual"`. No server-side slug, timestamp, or `manual:` prefix. UUID4 format is enforced so a submitted uid cannot collide with collector `{source}:{id}` values.

**Rejected:** `manual:{sha256(url)}` (kickoff) — url may be a shared careers page. `manual:{company-slug}-{title-slug}-{YYYYMMDDHHmmss}` (first decision) — overcomplicated, same-second overwrites, and forced a second poll path because re-POSTing minted a new uid. Server-minted uuid — the client still needs the id to poll; generating it client-side is the same uniqueness with less protocol.

**Consequence:** start and poll are the same `POST /jobs/submit` (Q10 closes). A new uuid is a new job; repeating a uuid is get-or-create/poll (Q7). No uid-helper module.

### Q4 — Skip screening; always assess; always generate a cover letter

**Decided:** 2026-09-19
No `ScreeningAgent` on this path. Always call fit assessment. Always generate a cover letter, ignoring `COVER_LETTER_MIN_CV_SCORE`. Pipeline gates for collected jobs are unchanged.

**Rejected:** run screening first — the user asked to evaluate *this* JD, not to apply the cheap corpus filter. Honouring the score gate — would leave a submitted job on the feed with no letter, and the user would have to hit generate anyway; the generate endpoint already bypasses the gate (cover-letter plan Q5).

**Consequence:** API lifespan does not construct `ScreeningAgent`. Background step 5 always attempts a letter unless `cover_letter_key` is already set.

### Q5 — Always insert; do not deduplicate

**Decided:** 2026-09-19
Do not call `CollectionService.deduplicate`. Every successful background run `upsert_jobs` the posting under the client uuid.

**Rejected:** reuse a scraped job with matching normalised title+company — would hide the pasted description behind a possibly stale corpus copy. Dedup-by-url — careers-page problem from Q3.

**Consequence:** `jobs` can contain both a scraped row and a uuid row for the same role. Only the submitter’s assessment index points at the submitted uid (Q6). Two different uuids for the same JD are two jobs.

### Q6 — Private to the submitting user

**Decided:** 2026-09-19
Persist in Mongo `jobs` (the only posting store) but do **not** embed into OpenSearch `jobs`. `store_assessment(..., job=job)` still writes the per-user denormalized assessment (Mongo + OpenSearch `assessments`), which is how the submitter’s feed shows the posting. No `private` / `submitter` field on `JobPosting`.

**Rejected:** corpus member (embed + let other users’ retrieval pick it up) — user asked for private. Separate per-user jobs collection — large model change; privacy is achieved by not indexing the corpus and by assessments being per-user. `build_pairs` already only searches current-cycle uids, so a Mongo-only row is not paired with other users on the next collect anyway.

**Consequence:** no `EmbeddingClient` in API lifespan. Tests assert the jobs-corpus index is not called.

### Q7 — Idempotent per uid, not per JD

**Decided:** 2026-09-19
For a given `(username, job_uid)`: a live pending/complete task is returned as-is; background retry reuses a stored assessment and an existing `cover_letter_key` and does not `insert_one` a second assessment. A POST with a **new** uuid is a new job and runs the LLMs again.

**Rejected:** get-or-create across submits by matching title+company — duplicate prevention is a non-goal (Q5). Regenerating a letter that already has a key — already out of scope on the generate endpoint.

**Consequence:** `get_assessment` / `get_application_cover_letter_key` guards in the handler (complete short-circuit) and in the background service, matching the pair node. Two feed items for two uuids of the same JD is expected.

### Q8 — Response is `{ job_uid, status }`; letter stays on existing GET routes

**Decided:** 2026-09-19
200 body is `{ "job_uid": str, "status": "pending" | "complete" }`. `failed` never appears. Once `complete`, the client uses `POST /jobs/search` and `GET /jobs/{job_uid}/cover-letter` (and pdf). Do not inline `JobFeedItem` or cover-letter JSON on this endpoint.

**Rejected:** return `JobFeedItem` on start — the assessment does not exist yet under accept-and-poll. Inline the letter on complete — duplicates `GET .../cover-letter` and pulls S3 into the poll path.

**Consequence:** one response model for start and poll. Status enum matches cover-letter generate.

### Q9 — `POST /jobs/submit`

**Decided:** 2026-09-19
Path is `POST /jobs/submit`.

**Rejected:** `POST /jobs` — reads as “write a job document” and occupies the REST create slot. `/jobs/manual` — fine, but `/submit` is the clearer verb. `POST /jobs/{job_uid}/submit` — unnecessary once the uid is in the body (Q3); would also occupy the `{job_uid}` slot next to `status` and `cover-letter`.

**Consequence:** one new route in `api/routes/jobs.py`.

### Q10 — Poll is the same `POST /jobs/submit`

**Decided:** 2026-09-19
No second path. The client holds the uuid it generated and repeats `POST /jobs/submit` until `status` is `complete`. Live pending/complete short-circuit; failed/expired pending is reclaimed.

**Rejected:** `GET /jobs/{job_uid}/submit` — was the leaning when the server minted the uid and a second POST would have created a new job. Client-generated uuid removes that constraint, and a GET with retry side effects was the weaker of the two options anyway. `POST /jobs/{job_uid}/submit` — extra route for no gain over uid-in-body.

**Consequence:** handler structure matches `generate_job_cover_letter` almost line for line. Phase 3 is one route.

## Implementation phases

### Phase 1 — Task model, request/response models, repository

**Depends on:** nothing (Q1–Q3, Q8–Q10 recorded)
**Reviewable when:** config keys exist; `ManualJobTask` includes `failed`/`error`; unique `(username, job_uid)` index; claim/get/complete/fail round-trip against test Mongo; claim is a no-op against live pending and complete; `ManualJobSubmitRequest` rejects non-UUID4 `job_uid` and accepts a uuid4.
**Touches:** `config.py`, `models/manual_job_task.py` (new; same shape as `CoverLetterTask`, separate collection — do not entangle the two), `models/jobs_api.py`, `repository/mongo_jobs_repository.py`, `ensure_manual_job_task_indexes` from API lifespan, tests in `tests/integration/test_mongo_jobs_repo.py` or a focused module

- Add `MONGODB_MANUAL_JOB_TASKS_COLLECTION = "manual_job_tasks"` and `MANUAL_JOB_TASK_TTL_SECONDS = 180`.
- Claim as atomic `find_one_and_update` with filter: missing (upsert) **or** `failed` **or** (`pending` and `expires_at < now`).

### Phase 2 — Background service (normalise → persist → assess → letter)

**Depends on:** Phase 1, Q4–Q7
**Reviewable when:** mocked-agent tests cover normalise failure, happy path, assessment reuse, cover-letter-key reuse, exception → `failed`; `upsert_jobs` called with `source="manual"` and the request uuid; OpenSearch jobs index not called; `store_assessment` passed the posting.
**Touches:** `job_submit_service.py` (new), `cover_letter_service.generate_and_persist_cover_letter` (call, do not fork)

Can proceed in parallel with Phase 1’s HTTP-adjacent models.

### Phase 3 — Endpoint + lifespan agents + tests

**Depends on:** Phase 1, Phase 2
**Reviewable when:** `POST /jobs/submit` matches the request flow; agents constructed in API lifespan; Tests list is green.
**Touches:** `main.py`, `api/deps.py`, `api/routes/jobs.py`, `tests/unit/test_manual_job_submit.py` (new), OpenAPI assertions in `tests/integration/test_jobs_api.py`

- Lifespan: `DeduplicationAgent`, `FitAssessmentAgent`, `CVTextExtractionAgent`, `ensure_manual_job_task_indexes`.
- Handler order: reportable task → assessment+key complete → profile/CV 404 → claim + `BackgroundTasks.add_task`.
- Background: helper sequence then `complete_manual_job_task`; on exception `fail_manual_job_task`.
