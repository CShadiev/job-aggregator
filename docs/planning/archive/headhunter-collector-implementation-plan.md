# HeadHunterCollector — Implementation Plan

**Status:** Draft
**Last updated:** 2026-09-13
**Open questions:** 5

---

## Problem

The pipeline currently collects jobs from LinkedIn (via Apify, three regional tasks) and Arbeitnow (direct API). None of these sources cover the Russian job market. hh.ru (HeadHunter) is the dominant job platform in Russia and exposes a public REST API ([документация](https://api.hh.ru/openapi/redoc)), so a direct-API collector — in the style of `ArbeitnowCollector` rather than an Apify scraper — is the natural way to add Russian coverage. Primary interest: Python-related jobs in Russia.

## Scope

### In scope

- New `HeadHunterCollector` in `collection_service/headhunter_collector.py` satisfying `ICollector`.
- Config entries for base URL, search parameters, page limits, User-Agent.
- Registration in `orchestration/deps.py:build_collectors`.
- Integration tests mirroring `tests/integration/test_arbeitnow_collector.py`.

### Out of scope

- Salary extraction (the `JobPosting` model has no salary field; adding one is a separate feature).
- OAuth authorization flow for user-scoped endpoints (only relevant if Q1 forces app-token auth, and even then it's a one-time token, not a flow in code).
- Areas outside Russia (the `area` parameter makes this a config change later).

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| Collector protocol | `collection_service/collector_protocol.py` | Must implement `get_source_name()` and `collect_jobs(min_date) -> CollectionResult`, with postings sorted by `posted_at` descending. |
| Checkpoint contract | `collection_service/collection_service.py:70-73` | `CollectionService` sets the source checkpoint to `postings[0].posted_at` — the collector **must** return newest-first, or the checkpoint regresses. hh.ru supports `order_by=publication_time` (newest first) which satisfies this server-side. |
| Reference implementation | `collection_service/arbeitnow_collector.py` | The pattern to follow: optional injected `ClientSession`, config-driven URL/limits, `collect(min_date, max_pages, skip_pages)` pagination loop, `_parse_job` → `JobPosting`, `cleanup()`. Note its retry (`sleep 30, retry forever` on 429/403) is **not** safe to copy — see Q5. |
| Output model | `models/collection_service.py` (`JobPosting`) | Required: `uid`, `source`, `title`, `company`, `location`, `remote`, `url`, `description_raw`, `posted_at`, `collected_at`. `description_raw` is required and feeds downstream screening — see Q2. |
| Registration | `orchestration/deps.py:build_collectors` | Add one instance to the returned list; shared `ClientSession` is passed in. |
| Config | `config.py` (see `ARBEITNOW_BASE_URL` / `ARBEITNOW_MAX_PAGES` at lines 24-25) | Add `HH_*` settings alongside. |
| Tests | `tests/integration/test_arbeitnow_collector.py` | Live-API integration tests; same shape applies, but see Q1 — the API may not be reachable from every environment. |
| Metrics | `monitoring/metrics.py:record_job_stage` | Takes `source` as a free-form label; no registration needed for a new source. |

## hh.ru API facts (verified)

- Endpoint: `GET https://api.hh.ru/vacancies`. Key params: `text` (query), `search_field` (`name` / `description` / `company_name`; default = all fields), `area` (`113` = Russia), `page` (0-based), `per_page` (max 100), `order_by=publication_time` (newest first), `period` (days, max 30) or `date_from`/`date_to` (ISO 8601, mutually exclusive with `period`).
- Response: `{items, found, pages, page, per_page}`. Depth cap: `page * per_page ≤ 2000` — deeper requests return `400`.
- List items carry `id`, `name`, `employer.name`, `area.name`, `published_at` (ISO 8601 with offset), `alternate_url`, `schedule` / `work_format`, `employment`, and only **snippets** of the description (`snippet.requirement`, `snippet.responsibility`). The full HTML `description` and `key_skills` require a per-vacancy `GET /vacancies/{id}` (Q2).
- Anonymous access is allowed for vacancy search, but a proper `User-Agent` of the form `AppName/version (contact@email)` is required — browser-style UAs are rejected with `400 bad_user_agent: blacklisted`.
- **Live probe result (2026-09-13, from this dev environment):** even with a well-formed UA, requests return a bare `403 {"errors":[{"type":"forbidden"}]}`. This smells like IP-range blocking (hh.ru is known to restrict datacenter / non-CIS IPs for anonymous access). This is the biggest feasibility risk — Q1.
- Vacancies auto-archive after ~30 days, so `period`/`date_from` beyond 30 days is moot; combined with checkpointing per run, the 2000-result depth cap is unlikely to bite for incremental runs.

## Design

### Collector shape

Mirror `ArbeitnowCollector`: constructor takes optional `ClientSession`, reads config; `get_source_name()` returns `"headhunter"`; `collect_jobs(min_date)` delegates to a paginating `collect()`. Differences from Arbeitnow:

- Pagination is 0-based with an explicit `pages` count in the response — the loop can stop at `page >= pages` or the 2000-depth cap instead of walking blind.
- `min_date` can be pushed server-side via `date_from` (rounded by the API to 5-minute granularity) in addition to the client-side stop condition, cutting wasted pages. Depends on Q4.
- Every request must send the configured `User-Agent` header.

### Field mapping (list item → `JobPosting`)

| `JobPosting` field | hh.ru source |
| --- | --- |
| `uid` | `f"headhunter:{item['id']}"` |
| `source` | `"headhunter"` |
| `title` | `name` |
| `company` | `employer.name` |
| `location` | `area.name` (city-level, e.g. "Москва") |
| `remote` | `work_format` contains `REMOTE`, falling back to `schedule.id == "remote"` |
| `url` | `alternate_url` (human-readable posting page, not the API URL) |
| `tags` | `key_skills` if full detail is fetched (Q2), else empty |
| `description_raw` | full `description` or joined snippets — depends on Q2 |
| `job_types` | `employment.id` (e.g. `full`), lower-cased |
| `posted_at` | `published_at` (ISO 8601 with offset; `ts_validator` normalises to UTC) |

### Search parameters

Depends on Q3. Baseline per the user: `text="python"`, `area=113` (Russia), `order_by=publication_time`, `per_page=100`.

### Error handling

Depends on Q5. What's already known: Arbeitnow's infinite `sleep(30)` retry on 403 would hang forever against hh.ru, where 403 can be a persistent captcha/IP block rather than transient rate limiting.

### Tests

Integration tests in the style of `tests/integration/test_arbeitnow_collector.py` (live API, max-pages cap, min_date stop, source/uid prefix assertions). Caveat from Q1: if the API is unreachable from CI/dev IPs, these tests will fail outside allowed networks and may need a skip marker or recorded fixtures — resolve together with Q1.

## Open questions

### Q1 — Is the API reachable from the runtime, and is anonymous access enough?

**Blocks:** everything — feasibility gate. Also decides the test strategy.
**Context:** A live probe from this dev environment on 2026-09-13 returned `403 forbidden` on `GET /vacancies` despite a correctly formatted `User-Agent` (browser UAs separately rejected as `blacklisted`). hh.ru is known to block datacenter/non-CIS IP ranges for anonymous requests. Options if the block reproduces from the real runtime: (a) register an application at dev.hh.ru and send an app access token (`Authorization: Bearer …` — a long-lived token, no OAuth dance in code), (b) route through a proxy in an allowed region, (c) accept that the collector only works from certain networks.
**Needed:** a probe from the environment where the pipeline actually runs — `curl -A "job-aggregator/1.0 (you@example.com)" "https://api.hh.ru/vacancies?text=python&area=113&per_page=1"`. If that returns 200 anonymously, this question closes cheaply.

### Q2 — Snippets or full descriptions for `description_raw`?

**Blocks:** field mapping, error handling (request volume), the `tags` mapping.
**Context:** The search listing only returns `snippet.requirement` / `snippet.responsibility` (a few hundred characters, sometimes null). The full HTML `description` and `key_skills` require one `GET /vacancies/{id}` per posting — for a 100-per-page run that's 100+ extra requests per page, which raises rate-limit exposure (hh.ru publishes no hard limits but throttles aggressively). Downstream, `description_raw` feeds the screening and fit-assessment agents, so its quality directly affects pipeline value; snippets alone are likely too thin for meaningful fit assessment.
**Leaning:** fetch full details with bounded concurrency (e.g. 5 parallel requests with a small delay), since description quality is the point of collecting at all. But this is the main cost/complexity driver of the feature, worth an explicit decision.

### Q3 — Search parameters: query, search_field, and any extra filters

**Blocks:** the search-parameters design section, config defaults.
**Context:** User suggests `text="python"`. Sub-decisions: (a) `search_field=name` (title-only, high precision, misses e.g. "Backend-разработчик" postings that mention Python only in the body) vs default all-fields (high recall, pulls in loosely related roles — but the pipeline already has screening agents downstream to absorb noise); (b) whether to pre-filter by `work_format`/`schedule` (remote-only?) or `professional_role`; (c) whether one query is enough or several (`python`, `backend`, …) — multiple queries also sidestep the 2000-depth cap if it ever binds. Note: results will be mostly Russian-language; downstream normalization/screening agents will receive Russian text.
**Leaning:** start with the user's suggestion — single `text="python"`, default all-fields search, no extra filters — and let downstream screening do the filtering, consistent with how Arbeitnow feeds the pipeline. Cheap to revisit via config.

### Q4 — Incremental collection: server-side `date_from`, client-side stop, or both?

**Blocks:** the pagination loop design; interacts with the checkpoint contract.
**Context:** `CollectionService.collect` passes the stored checkpoint as `min_date`. Arbeitnow honours it purely client-side (stop when an older posting appears). hh.ru can filter server-side with `date_from` (rounded to 5 minutes — so up to 5 minutes of overlap/re-fetch, which UID dedup in `CollectionService.deduplicate` already absorbs). Server-side filtering saves pages and keeps runs inside the 2000-depth cap.
**Leaning:** both — pass `date_from=min_date` and keep the client-side stop as a guard. Low controversy; could be batched with Q3.

### Q5 — Retry/backoff policy for 403/429 and captcha responses

**Blocks:** error-handling section.
**Context:** `ArbeitnowCollector.collect` (`collection_service/arbeitnow_collector.py:92-94`) retries 429/403 forever with 30s sleeps. Against hh.ru a 403 can be a *persistent* condition (IP block, captcha demand) — copying that pattern means the pipeline hangs indefinitely. Also relevant: hh.ru returns `400` for known-bad requests (depth cap exceeded, bad UA), which should fail fast, not retry.
**Leaning:** bounded retries (e.g. 3 attempts with backoff) for 429/5xx; treat 403 as fatal for the run — log and return what was collected so far (or raise, depending on how partial results should count against the checkpoint). The partial-result-vs-raise choice is the part that needs a real decision.

## Decision log

Empty — no decisions recorded yet.

## Suggested question sequence

1. **Q1** — feasibility gate; everything else is moot if the runtime can't reach the API. Needs a probe from the real runtime environment, which only the user can run.
2. **Q3 + Q4** — cheap, low-controversy, can be batched in one short session; settles config defaults and the pagination loop.
3. **Q2** — the main cost/complexity decision; deserves its own deliberation, informed by Q1's outcome (auth mode affects rate-limit headroom).
4. **Q5** — mostly mechanical once Q1/Q2 fix the request volume and auth mode; the one real choice is partial-results-vs-raise on fatal errors.

## Implementation phases

Skeletal until finalization.

### Phase 1 — Collector + config

**Depends on:** Q1–Q5
**Touches:** `collection_service/headhunter_collector.py` (new), `config.py`

### Phase 2 — Registration + tests

**Depends on:** Phase 1
**Touches:** `orchestration/deps.py`, `tests/integration/test_headhunter_collector.py` (new)
