# Demo Access — Implementation Plan

**Status:** Implemented
**Last updated:** 2026-09-30
**Open questions:** 0
**Origin:** Recording the UI for [`readme-landing-page-and-evals-showcase-implementation-plan.md`](readme-landing-page-and-evals-showcase-implementation-plan.md) would put the author's own job feed, scores, and cover letters on screen. That plan left a demo account out of scope (its Q10). This plan is that account: a fictional candidate, a login that does not ask the visitor for a password, a daily cap on the two endpoints that spend LLM money, and a one-shot pipeline run so the demo feed is populated without joining the scheduled worker.

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done) · `Implemented` (shipped).

---

## Problem

The live instance at `https://cshadiev.dev` is a single real user. `get_current_user` (`api/deps.py:24-32`) turns an Auth0 access token into `User.username` from the userinfo `name` claim, and every feed, assessment, and cover letter is stored under that username. There is no second profile. The scheduled worker loads **every** document in `user_profiles` (`orchestration/nodes/batch.py:199` via `get_user_profiles`) and pairs those users with each newly collected batch. Adding a demo profile with no other change would put that profile on the 12-hour cycle (`config.py:125`, `PIPELINE_SCHEDULE_SECONDS`) and spend screening, assessment, and cover-letter calls on it forever.

Login is `POST /users/login` with a username and password (`api/routes/users.py:13-28`), which calls Auth0 Resource Owner Password Grant (`auth_service.py:86-121`). A visitor cannot reach the UI without those credentials. Putting the demo password in the README or the client is the thing this plan exists to avoid.

Two authenticated endpoints call the LLM from the API process, on demand, for whatever the signed-in user submits:

- `POST /jobs/submit` (`api/routes/jobs.py:70`) — normalise, fit-assess, and always draft a cover letter (`job_submit_service.py`).
- `POST /jobs/{job_uid}/cover-letter/generate` (`api/routes/jobs.py:212`) — draft a letter for a job that is already assessed.

Neither is capped. On a shared public account those two routes are the spend.

The demo feed also has to exist before anyone logs in. The compiled pipeline always starts at `collect` (`orchestration/graph.py:57`), which scrapes new postings and then pairs every profile. There is no entry point that says "run the pair subgraph for this one user over jobs already in Mongo."

## Scope

### In scope

- A fictional candidate: a committed `UserProfile` fixture, a PDF CV rendered from it, and a seed script that upserts the profile into `user_profiles` and uploads `cv.pdf` (Q1).
- `POST /users/demo-login`, no request body, returning the same `LoginResponse` as `/users/login`. The server holds the demo password and performs the existing Auth0 password grant (Q2).
- Two independent daily caps, demo user only: 10 new manual job submissions and 10 new cover-letter generations, UTC calendar day (Q3).
- The scheduled worker skips the demo username in `build_pairs` (Q4).
- A manual script that runs retrieval plus the existing pair subgraph for the demo user over the 100 most recently collected non-manual jobs (Q5).

### Out of scope

- README copy, the hero GIF, and any change to the landing-page plan. This plan makes a non-personal account exist so that recording can happen later.
- The React client (`react-app/` is a separate repository and gitignored here). The contract the client needs is `POST /users/demo-login` → `LoginResponse`, then the existing bearer-token flow. The button is not built in this repo.
- A local zero-credential stack (roadmap action 2): no stubbed LLMs, no seeded Mongo snapshot, no `DEMO_MODE` that bypasses Auth0.
- Per-visitor isolation. One shared demo user. Visitors see and overwrite the same application statuses and cover letters (Q2).
- Capping the author's account, `PATCH` status updates, or `PATCH` cover-letter edits. Those do not call an LLM (Q3).
- Creating the Auth0 user from code. That user is created in the Auth0 dashboard; the seed script only writes Mongo and S3 (Q1, Q2).
- Changing what the scheduled cycle collects, or indexing `source: "manual"` jobs into OpenSearch.

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| Current user | `api/deps.py:24-32` | `User.username` is userinfo `name`, not the login string. The Auth0 user's Name, the fixture `username`, and `DEMO_USERNAME` must be the same value or the feed looks up an empty profile. |
| Login | `api/routes/users.py:13-42`, `auth_service.py:86-131` | Password grant already returns `access_token`, `id_token`, `expires_in`, `refresh_token`. Demo login calls `authenticate` and returns that dict. `get_current_user` stays unchanged because the token is a normal Auth0 access token. |
| Profile document | `models/users.py:160-180`, `repository/mongo_jobs_repository.py:340-388` | `UserProfile` is what prompts see. `cv_text` and `cv_source_sha256` live on the same Mongo document and are **not** fields of `UserProfile` (`extra="ignore"`). A seed must not put the CV rendering on the model. |
| CV object | `repository/object_storage.py:138-162` | PDF at `{ROOT}/{username}/cv.pdf`. `upload_user_cv` / `get_user_cv` already exist. `POST /jobs/submit` 404s when the object is missing (`api/routes/jobs.py:106-108`). |
| CV text | `cv_text_service.py:11-30` | `ensure_cv_text` hashes the PDF and calls `CVTextExtractionAgent` only when the hash changes. The profile seed runs it once so the batch script does not discover a bad PDF after spending on retrieval. |
| No profile write API | `api/routes/users.py` | Login and refresh only. The fixture is loaded by a script, same as every current profile. |
| Worker fan-out | `orchestration/nodes/batch.py:195-222` | `build_pairs` fetches all profiles, then top-K retrieval per profile (`PIPELINE_PAIR_MODE=topk`, ratio 0.5). Exclusion belongs here. `get_user_profiles` itself stays unfiltered: `scripts/export_fit_assessment_benchmark_dataset.py` also calls it. |
| Pair idempotence | `orchestration/nodes/pair.py:70-73`, `98-102`, `128-131` | Stored screening, assessment, and cover letter are reused. Re-running the seed script does not pay again for pairs it already finished. |
| Graph entry | `orchestration/graph.py:57-61` | `START → collect → normalize → dedupe → persist → embed → build_pairs`. Invoking this graph would scrape and would pair every remaining user. The seed script does not call it. |
| Worker thread | `orchestration/runner.py:41-42`, `config.py:124` | Checkpointer thread id is `PIPELINE_THREAD_ID` (`job-pipeline`). The pair subgraph is compiled **without** a checkpointer (`orchestration/graph.py:36`). The script uses that subgraph, so it cannot resume the worker's thread. |
| Retrieval window | `orchestration/nodes/batch.py:263-265`, `config.py:98-101` | `k = min(max(ceil(n * 0.5), 1), 200)`. For 100 jobs, k = 50. Screening runs on those 50 pairs; assessment and letters follow the existing gates. |
| Letter gate | `orchestration/routing.py:17-29`, `config.py:116` | Cover letter only when `cv_ats_match_score >= COVER_LETTER_MIN_CV_SCORE` (80). The seed uses this gate. It does not force a letter for every job. |
| Manual jobs | `job_submit_service.py:19`, `27` | `source="manual"`. Those rows are not embedded into the OpenSearch `jobs` index. A "most recently added" query that includes them would hand retrieval uids it cannot hit. |
| Job recency | `models/collection_service.py:54-57` | `collected_at` is when the collector stored the posting. That is "most recently added," not `posted_at`. |
| Submit / letter tasks | `repository/mongo_jobs_repository.py:537-587`, `638-688` | Unique on `(username, job_uid)`. `created_at` is `$setOnInsert` only. Polls of a live pending or complete task return before a new claim (`api/routes/jobs.py:92-101`, `237-240`). A failed task can be claimed again without a new `created_at`. |
| PDF library | `tools/pdf_generator.py` | fpdf2 is already a dependency, used for cover letters. The CV renderer is a separate function; it does not go through `CoverLetterContent`. |
| Sample profile | `tests/datasets/cover_letter_sample.py:29` | Shows a valid `UserProfile` shape (fictional "Ada Lindqvist"). The demo fixture is its own file so production seed data is not imported from the test suite. |
| CORS | `main.py:97-98` | `POST` is already allowed. Demo login needs no CORS change. |
| Client | `react-app/` gitignored | "Sign in as demo" is a client-repo change against the contract above. |

## Design

### Demo identity

Fixture path: `fixtures/demo/profile.json`, validated as `UserProfile` in a unit test. Username is `demo`.

The person is fictional. No name, employer, email, or profile URL of the author. Contact email is on `example.com`. The career is a software-engineering profile aimed at the markets the collectors actually fill (LinkedIn DE / UK / PL / US, Indeed, StepStone, Arbeitnow), including work authorisation that does not make every assessment a sponsorship rejection. Otherwise the seeded feed is an empty low-score list and the UI recording has nothing to show. The biography itself is written in the fixture during Phase 1 and reviewed in that diff; it is not specified further here.

`scripts/seed_demo_profile.py` (console script `seed-demo-profile`):

1. Refuse to run unless `DEMO_USERNAME` equals the fixture username.
2. Render a plain multi-page PDF from the fixture with fpdf2 and upload it via `upload_user_cv`.
3. Upsert the profile with `$set` of `UserProfile.model_dump()`. That writes the prompt-facing fields and does not unset `cv_text` / `cv_source_sha256`.
4. Call `ensure_cv_text` so the PDF is extracted once and the hash is stored. A later upload of a different PDF invalidates the hash on the next call, which is the existing rule.

Re-running the script overwrites the profile fields and the PDF. It does not delete assessments, screenings, or cover letters.

Operator step, not code: in the Auth0 dashboard, create a database user whose **username and Name** are both `demo`, with a password stored only as `DEMO_PASSWORD`. Password grant is already how `/users/login` works. The API cannot see the user until Name matches, because `get_current_user` reads `name`.

### Demo login

`POST /users/demo-login`. No body.

When `DEMO_USERNAME` or `DEMO_PASSWORD` is unset, respond **404**. Deployments that are not hosting the demo do not advertise the route as a failed login.

When both are set, call `Auth0ClientWrapper.authenticate(DEMO_USERNAME, DEMO_PASSWORD)` and return `LoginResponse`. Same error mapping as `/users/login` (401 on `ValueError`). The handler logs the username and never the password. It does not accept a username or password from the client, so it cannot be used as an open proxy for other accounts.

The access token is an Auth0 token for that one user. Refresh uses the existing `POST /users/refresh`. Session length is Auth0's, not a local JWT.

Every caller of this route becomes the same user. Application status and cover-letter text are shared. That is the account the UI recording and a reviewer both see. The cost bound is Q3, not a second user per visitor.

### Daily caps

Config, demo user only (the username on the token equals `DEMO_USERNAME`):

- `DEMO_DAILY_MANUAL_JOB_LIMIT` default `10` — `POST /jobs/submit`
- `DEMO_DAILY_COVER_LETTER_LIMIT` default `10` — `POST /jobs/{job_uid}/cover-letter/generate`

Any other username is unchanged. When `DEMO_USERNAME` is unset, neither cap runs.

The cap counts task documents for that username whose `created_at` falls on the current UTC calendar day. It is applied only on the path that would **insert** a new task:

- A poll of a pending or complete task still returns the current status and does not consult the cap. The client's start-and-poll loop must keep working after the tenth success.
- A `job_uid` that already has a task (including a failed one) is a retry of that submission, not a new one, and is not refused for quota. `created_at` does not move, so a retry does not consume a second slot.
- A new `job_uid` when the day's count is already at the limit gets **429** with a stable `detail` string, before `claim_pending_*`. No background task is scheduled.

`POST /jobs/submit` already drafts a cover letter inside the submit task. That letter does not write a `cover_letter_tasks` document and does not consume the cover-letter cap. A later `POST .../cover-letter/generate` for a job that already has `cover_letter_key` returns `complete` immediately and does not count either.

A concurrent pair of requests can both observe count 9 and both insert. An overshoot of one or two on a cap of ten is accepted. This is not a billing ledger.

### Worker exclusion

`build_pairs` drops profiles whose `username` equals `DEMO_USERNAME` before retrieval and before `ensure_cv_text`. It logs the skipped username at info. `get_user_profiles` is not filtered. When the env var is unset, the node behaves as it does today.

The demo user remains readable by `get_user_profile` for the API and for the seed script. Exclusion is only the scheduled fan-out.

### Pipeline seed script

`scripts/seed_demo_pipeline.py` (console script `seed-demo-pipeline`). Optional `--limit`, default `100`.

1. Refuse unless `DEMO_USERNAME` is set, the profile exists, and `get_user_cv` succeeds.
2. Load that many jobs from `jobs`, `source != "manual"`, sort `collected_at` descending.
3. Run the same top-K retrieval `build_pairs` uses (extracted so the script and the node share one function) for that single profile, restricted to those uids.
4. For each hit, invoke the compiled pair subgraph (`build_pair_subgraph`) with `new_pair_state`. Concurrency is `PIPELINE_PAIR_CONCURRENCY`. Screening, the assessment gate, and the score gate behave as in the worker. Metrics recorded by those nodes will show the run; that is one real cycle of spend, not a separate accounting path.

The script logs `n_jobs`, `k`, and `n_pairs`. Jobs in the Mongo window that are missing from the OpenSearch `jobs` index simply do not come back as hits.

It is manual. Nothing schedules it. Run it once after `seed-demo-profile` on the instance that holds the corpus, and again later when the demo feed should catch up with newer postings. Pairs already stored are skipped by the pair nodes.

Expected first-run spend on the default window: one CV extraction (if the profile seed has not already done it), one profile embedding, up to 50 screening calls, then assessment only for pairs the screen keeps, then a cover letter only for assessments at or above 80. That is the pipeline the UI is supposed to show.

## Open questions

None. All questions are in the Decision log.

## Decision log

### Q1 — Committed fictional fixture; seed writes Mongo and S3

**Decided:** 2026-09-30
The candidate is a new `UserProfile` JSON under `fixtures/demo/profile.json`, username `demo`. A script renders the PDF, uploads `cv.pdf`, upserts the profile document, and runs `ensure_cv_text`. The Auth0 user is created by hand with username and Name both set to `demo`.

**Rejected:** Seeding from `tests/datasets/cover_letter_sample.py` — couples the live account to a test helper and to the name used in unit tests. Hand-writing `cv_text` into the fixture — the rendering has to come from the PDF the pipeline will hash, or the next `ensure_cv_text` disagrees with what we stored. A profile-create HTTP API — there is no writer today, and a public one is a different product.

**Consequence:** Phase 1 includes the biography. Review that diff as the privacy check: fictional person, `example.com` contact, no author identifiers. Re-running the seed refreshes the profile and the PDF and leaves existing assessments in place.

### Q2 — Demo login is server-side Auth0 password grant

**Decided:** 2026-09-30
`POST /users/demo-login` calls `authenticate` with `DEMO_USERNAME` and `DEMO_PASSWORD` from the environment and returns `LoginResponse`. Unset configuration is 404. The client sends no credentials. Tokens stay Auth0 JWTs, so `get_current_user` is unchanged.

**Rejected:** A locally signed JWT — `get_current_user` calls Auth0 userinfo (`api/deps.py:31`); a local token would need a second auth path. Returning a long-lived static access token — Auth0 access tokens expire and cannot be revoked (the revoke path is refresh tokens only, `auth_service.py:170-173`). Publishing the demo password — that is the flow this endpoint replaces.

**Consequence:** The route is unauthenticated on purpose. Anyone who can reach the API can act as `demo`. Shared mutable state (statuses, letter text) is accepted. The password lives only in the API environment and is never logged. The React button is a follow-up in the client repository; until it exists, the route can still be called directly.

### Q3 — Ten new manual submits and ten new cover-letter generations per UTC day, demo user only

**Decided:** 2026-09-30
Independent caps, default 10, overridable by `DEMO_DAILY_MANUAL_JOB_LIMIT` and `DEMO_DAILY_COVER_LETTER_LIMIT`. Count is task documents with `created_at` on the current UTC day. Only a request that would insert a new `(username, job_uid)` task is refused, with 429, before claim. Polls and retries of an existing task are not refused. The letter produced inside `POST /jobs/submit` does not consume the cover-letter cap. Other usernames, and non-LLM mutations, are not capped.

**Rejected:** One shared pool of 10 — "for both" is two actions. A global cap — would change the author's own submit and letter flow; the spend being bounded is the public account. Rolling 24 hours — "per day" is a calendar day, and the day's boundary should not depend on when the first request arrived. Counting every retry as a new slot — a failed task could not be retried once the day was full, and `created_at` is insert-only so the document model does not have a per-attempt counter.

**Consequence:** A visitor can still edit statuses and overwrite letter JSON. Those routes do not call a model. Concurrent requests may exceed the cap by a small number. Exhausting the cap blocks every visitor of the shared account until the next UTC day.

### Q4 — Skip the demo user inside `build_pairs` only

**Decided:** 2026-09-30
When `DEMO_USERNAME` is set, `build_pairs` removes that profile from the list it retrieves and pairs. The repository method that returns all profiles stays as it is.

**Rejected:** A flag on the Mongo document filtered inside `get_user_profiles` — the export script would silently lose the demo profile, and `UserProfile` would grow a field that `model_dump_json` would inject into fit-assessment and cover-letter prompts. Deleting the profile between worker runs — the API would 404 for the demo user.

**Consequence:** A worker cycle with only the demo profile in the collection builds zero pairs and finalizes. The demo user's CV is not re-extracted on the worker. Cost of keeping the account is the one-shot script in Q5, plus whatever visitors do under Q3.

### Q5 — Seed script runs retrieval and the pair subgraph on the latest 100 collected jobs

**Decided:** 2026-09-30
`seed-demo-pipeline` reads the 100 newest `jobs` documents with `source != "manual"` ( `--limit` overrides), retrieves top-K for the demo profile only, and invokes `build_pair_subgraph` per hit. It does not call `collect` and does not use `PIPELINE_THREAD_ID`.

**Rejected:** `uv run run-pipeline` — starts at `collect`, scrapes, and pairs every non-excluded user; it cannot be aimed at an existing Mongo window. `POST /jobs/submit` in a loop — skips screening, always writes a letter, and would also burn the daily cap. Cartesian pairing of all 100 — pays assessment on pairs the production gate would have dropped; the demo would show a different product than the worker.

**Consequence:** First run is real LLM spend, bounded by the production gates (about 50 screens, then the survivors). Re-runs are cheap where results already exist. The script is not on the 12-hour schedule. Jobs absent from the OpenSearch `jobs` index are absent from the demo feed for that run.

## Implementation phases

### Phase 1 — Fixture and profile seed

**Depends on:** nothing
**Reviewable when:** `fixtures/demo/profile.json` validates as `UserProfile` with username `demo` and contains no author identifiers; `seed-demo-profile` upserts that document, uploads the PDF, and leaves a `cv_text` artifact whose hash matches the uploaded bytes; a second run does not delete assessments.
**Touches:** `fixtures/demo/profile.json`, `scripts/seed_demo_profile.py`, a small CV PDF renderer, `pyproject.toml` script entry, unit tests for fixture validation and the upsert/`$set` shape (object storage and the extraction agent mocked)

Operator checklist after this phase, on the target environment: create the Auth0 user (Q1), set `DEMO_USERNAME` and `DEMO_PASSWORD`, run `seed-demo-profile`.

### Phase 2 — Demo login

**Depends on:** Phase 1 for a profile that the resulting token can actually read; the route itself can land against a mocked `authenticate`
**Reviewable when:** `POST /users/demo-login` returns 404 when either demo env var is unset, returns `LoginResponse` from `authenticate(DEMO_USERNAME, DEMO_PASSWORD)` when both are set, and rejects a body that tries to pass a different username. Password does not appear in logs.
**Touches:** `config.py`, `api/routes/users.py`, `tests/unit` coverage next to the existing login tests

### Phase 3 — Daily caps

**Depends on:** Phase 2's `DEMO_USERNAME` (no-op when unset)
**Reviewable when:** the demo user receives 429 on the 11th new `job_uid` of the UTC day for submit and, separately, for cover-letter generate; a poll or a retry of an existing uid still returns the task status; a different username is never capped; a submit-path letter does not increment the cover-letter count.
**Touches:** `api/routes/jobs.py`, `repository/mongo_jobs_repository.py` (count by username and `created_at`), `config.py`, `tests/unit/test_manual_job_submit.py`, `tests/unit/test_manual_cover_letter_generation.py`

### Phase 4 — Worker exclusion and pipeline seed

**Depends on:** Phase 1 (profile and CV must exist to run the script). Exclusion can land before the script.
**Reviewable when:** `build_pairs` omits `DEMO_USERNAME` and still pairs every other profile; with the var unset, the node is unchanged; `seed-demo-pipeline --limit 100` loads non-manual jobs by `collected_at` desc, retrieves with the shared top-K helper, and invokes the pair subgraph only for the demo user, without calling `collect`.
**Touches:** `orchestration/nodes/batch.py` (filter plus extracted retrieval helper), `scripts/seed_demo_pipeline.py`, `pyproject.toml`, `repository/mongo_jobs_repository.py` (recent-jobs query), `tests/unit/test_build_pairs_gating.py`, a unit test for the script's job query and profile selection with mocked agents

Run `seed-demo-pipeline` by hand on the live corpus after Phase 1's operator checklist. That run is the spend described in Q5. CI does not run it.
