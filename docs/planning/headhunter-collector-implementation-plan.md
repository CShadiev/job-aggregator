# HeadHunter collector — Implementation Plan

**Status:** Ready for implementation
**Last updated:** 2026-10-10
**Open questions:** 0

## Summary

Add an hh.ru collector that scrapes HTML in two steps — download a search-results page, read vacancy ids, download each vacancy page, read the job description — and plug it into the worker the same way Arbeitnow is plugged in: an `ICollector` registered in `build_collectors`, so the existing `collect` node runs it. No new LangGraph node.

Requests are one at a time, with at least 200ms between them. Pagination stops on an empty search page, on the checkpoint, or on a page cap. A vacancy missing an essential field is dropped for good and counted in Prometheus; a missing `remote` flag is not a reason to drop it.

An earlier plan (`docs/planning/archive/headhunter-collector-implementation-plan.md`) targeted the public REST API. A probe on 2026-09-13 got `403` from this environment. Fetching the public HTML pages with a browser User-Agent works. This plan replaces the API approach; the archive stays as history.

## Current state

There is no hh.ru collector. A direct HTTP fetch of the public pages works from this environment; a browser is not required. The request that succeeded uses a 30-second timeout and these headers:

- `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36`
- `Accept: text/html,application/xhtml+xml`
- `Accept-Language: ru-RU,ru;q=0.9,en;q=0.8`

Search page: `GET https://hh.ru/search/vacancy` with the query below. Vacancy page: `GET https://hh.ru/vacancy/{id}`.

| Param | Value | Observed on a page fetched 2026-10-10 |
| --- | --- | --- |
| `text` | `python разработчик` | — |
| `area` | `1` | Vacancy address is Москва |
| `experience` | `between3And6` and `moreThan6` | Card label "Опыт 3-6 лет" |
| `employment_form` | `FULL` | Vacancy page: "Полная занятость" |
| `label` | `accept_labor_contract` | — |
| `search_period` | `7` | Pager shows 4 pages for this query |
| `accept_temporary` | `false` | — |
| `order_by` | `publication_time` | Newest first |
| `salary` | empty | — |
| `ored_clusters` | `true` | — |
| `page` | omitted on page 1 | Pager links pass `page` (0-based: the "2" link is `page=1`) |

`hhtmFrom=vacancy_search_list` and `hhtmFromLabel=vacancy_search_line` were also on that URL. They are referral tags, not filters. Past the last page, hh.ru does not 404: the response is a normal search page with no vacancy cards. A loop that only stops on an exception or on `min_date` will keep requesting forever when every returned vacancy is still newer than the checkpoint, which is the usual case on a cold start.

Parsing that worked, with BeautifulSoup's `html.parser`:

- Vacancy ids: every tag whose class starts with `vacancy-card--`. The `id` attribute is the vacancy id; a tag with no `id` is skipped. One search page had 20 such cards. The class suffix is a hash (`vacancy-card--n77Dj8TY8VIUF0yM`).
- Title: `h1` inside `div.vacancy-title`, `get_text(separator=" ", strip=True)`. No `div.vacancy-title`, or no `h1` inside it, means the page is not a posting.
- Company: `span.vacancy-company-name`, same text extraction. A missing node means the page is not a posting.
- Description: `div.vacancy-description`, `get_text(separator="\n", strip=True)`. A missing node means the page is not a posting.

Nothing from those pages is mapped onto `JobPosting` yet.

`JobPosting` (`models/collection_service.py:17`) also requires `location`, `remote`, `url`, `posted_at`, and `collected_at`. `tags` and `job_types` default to empty. The vacancy page's `application/ld+json` `JobPosting` block carries `title`, `datePosted` (`2026-10-10T12:59:06.188+03:00`), `description` (HTML), `hiringOrganization.name`, `jobLocation.address.addressLocality`, and `identifier.value`. It does not carry `employmentType` or `jobLocationType`. Those show up as text nodes: `data-qa="work-formats-text"` ("Формат работы: удалённо"), `data-qa="common-employment-text"` ("Полная занятость"), `data-qa="vacancy-address-with-map"` ("Москва"). The same `datePosted` value appears as `creationTime` inside the search page's `HH-Lux-InitialState` blob. `data-qa` attributes (`serp-item__title`, `vacancy-serp__vacancy-employer`, `pager-page`) are stable strings.

Arbeitnow is the collector to mirror, not the transport. `ArbeitnowCollector` (`collection_service/arbeitnow_collector.py`) takes an optional `ClientSession`, implements `get_source_name` / `collect_jobs(min_date) -> CollectionResult`, paginates in `collect(min_date, max_pages, skip_pages)`, and parses each item in `_parse_job`. When `min_date` is set, `collect_jobs` passes `max_pages=None` and stops at the first posting with `posted_at <= min_date` (`arbeitnow_collector.py:43-51`, `103-104`). With no `min_date`, it caps at `ARBEITNOW_MAX_PAGES` (`config.py:24-25`). It also keeps only postings whose description contains `"python"` (`filter_jobs`, line 39). A 429/403 sleeps 30s and retries the same page forever (lines 92-94).

`ICollector` (`collection_service/collector_protocol.py:25`) requires postings sorted by `posted_at` descending. `CollectionService.collect` (`collection_service/collection_service.py:58-73`) walks collectors in list order, passes each source's checkpoint as `min_date`, and — if the result has any postings — sets that source's checkpoint to `postings[0].posted_at`. There is no `try/except` around a collector. An exception leaves the `collect` node before it returns state: collectors that already ran have their checkpoints advanced, and their postings are discarded with the exception. The docstring on `collect` says checkpoints are not updated here; the code does update them. The code is the contract.

The worker graph has one collect node. `build_pipeline_graph` (`orchestration/graph.py:47-56`) starts at `collect`, which calls `collection_service.collect()` (`orchestration/nodes/batch.py:41-44`). Invalid entries from a collector are stored as `failed_tasks` with `node="collect"` (`batch.py:50-59`). Successful postings are counted on `job_descriptions_total{stage="collection"}` via `record_job_stage` (`batch.py:68-69`, `monitoring/metrics.py:266`). That counter's `stage` label is a closed set (`collection`, `retrieval`, `screening`, `assessment`); recording helpers swallow their own errors so telemetry cannot fail a cycle. Collectors are built in `build_collectors` (`orchestration/deps.py:51-85`): three Apify LinkedIn collectors, then `ArbeitnowCollector(client=client_session)`. The shared session is owned by the runner, not by the collector. Nothing in the repo calls `cleanup()`.

`description_raw` is sent to screening, fit assessment, and cover-letter generation as part of the job payload (`agents/fit_assessment.py:16-28`). `remote` is a boolean filter on the jobs query (`repository/mongo_jobs_repository.py:917`). `job_types` is stored as a keyword (`search/mappings.py`). `beautifulsoup4` and `aiohttp` are already dependencies (`pyproject.toml`). The metric catalogue lives in `docs/architecture.md` (the table around line 178).

## Design

### Collector

New `HeadHunterCollector` in `collection_service/headhunter_collector.py`.

- `get_source_name()` returns `"headhunter"`. uids are `headhunter:{vacancy_id}`.
- Constructor takes an optional `ClientSession`, same as Arbeitnow. Requests go through that session with the User-Agent, Accept, and Accept-Language headers listed above, and a 30-second timeout. The collector does not close a session it did not create.
- One request at a time. After each response, wait `HH_REQUEST_DELAY_SECONDS` (default `0.2`) before the next request. That gap applies between the search page and the first vacancy, between vacancies, and between the last vacancy and the next search page. No sleep before the first request (Q3).
- `collect_jobs(min_date)` walks search pages newest-first. Do not copy `filter_jobs`: the search query is the filter. A `"python"` substring check would drop Russian descriptions that never use the Latin word. Do not copy the infinite 429/403 sleep.
- Fetch path: search HTML → vacancy ids in page order → `GET https://hh.ru/vacancy/{id}` for each id. Pagination adds `page={n}` (0-based) to the same query. Ids come from the card `id` attribute. Vacancy fields come from JSON-LD, with the class-name fallbacks in Field mapping (Q4).
- Results stay in search order (`order_by=publication_time`), which is newest-first, so `postings[0]` is the checkpoint the service will store. The vacancy whose `posted_at <= min_date` is not included.

The pagination loop stops when any of these is true:

1. A search page returns HTTP success and yields zero vacancy ids (Q6). An out-of-range `page` is this case, not a 404.
2. A vacancy's `posted_at <= min_date`.
3. `HH_MAX_PAGES` search pages have been fetched. The cap applies on every run, including runs that have a `min_date`. Arbeitnow drops its cap when `min_date` is set; this collector does not, so a missed empty page cannot spin the cycle.

A failed search-page request is not an empty page. See Error handling.

### Field mapping

JSON-LD `JobPosting` is the source for every field it actually carries. Class-name and `data-qa` nodes fill the gaps. Description text is plain, not HTML: take the JSON-LD `description` (or the fallback node) and run it through `get_text(separator="\n", strip=True)`.

| `JobPosting` | Primary | If missing |
| --- | --- | --- |
| `uid` | `headhunter:{card id}` | Drop the vacancy (Q2) |
| `source` | `"headhunter"` | — |
| `title` | JSON-LD `title` | `h1` under `div.vacancy-title`. Still missing → drop |
| `company` | JSON-LD `hiringOrganization.name` | `span.vacancy-company-name`. Still missing → drop |
| `location` | JSON-LD `addressLocality` | `data-qa="vacancy-address-with-map"`. Still missing → `""`. Do not drop |
| `remote` | `data-qa="work-formats-text"` contains `удалённо` | `false`. JSON-LD has no `jobLocationType` on the fetched page. Do not drop |
| `url` | `https://hh.ru/vacancy/{id}` | Derived from the id |
| `tags` | — | `[]` |
| `description_raw` | JSON-LD `description`, reduced to plain text | `div.vacancy-description`, same reduction. Still missing → drop |
| `job_types` | `["full"]` when `data-qa="common-employment-text"` is "Полная занятость" | `[]` for any other or missing label. Do not drop |
| `posted_at` | JSON-LD `datePosted` | Drop the vacancy. `ts_validator` normalises the offset to UTC |
| `collected_at` | `datetime.now` | — |

`applicantLocationRequirements` on the fetched page is the country ("Россия"), not a remote flag. Do not read `HH-Lux-InitialState`. Salary stays unmapped: `JobPosting` has no salary field.

Essential fields are the ones that make a posting usable or checkpointable: id, title, company, description, `posted_at`. `remote`, `location`, and `job_types` are not essential. A failure to read them stores the default in the table and keeps the posting.

### Worker graph

Append `HeadHunterCollector(client=client_session)` to the list returned by `build_collectors` (`orchestration/deps.py:61`). The `collect` node, checkpointing, normalisation, and dedupe already run for every collector. The collector does not raise for fetch failures (Q2), so its position in the list does not decide whether earlier sources survive the cycle. It goes last, after Arbeitnow.

### Config

Add settings next to `ARBEITNOW_*` in `config.py`. Defaults are the query in Current state (Q1). `order_by` stays `publication_time`; the checkpoint contract depends on newest-first.

| Setting | Default |
| --- | --- |
| `HH_USER_AGENT` | the User-Agent string in Current state |
| `HH_TEXT` | `python разработчик` |
| `HH_AREA` | `1` |
| `HH_EXPERIENCE` | `between3And6`, `moreThan6` (repeated query param) |
| `HH_EMPLOYMENT_FORM` | `FULL` |
| `HH_LABEL` | `accept_labor_contract` |
| `HH_SEARCH_PERIOD` | `7` |
| `HH_ACCEPT_TEMPORARY` | `false` |
| `HH_ORDER_BY` | `publication_time` |
| `HH_ORED_CLUSTERS` | `true` |
| `HH_MAX_PAGES` | `10` |
| `HH_REQUEST_DELAY_SECONDS` | `0.2` |

`HH_MAX_PAGES` is a backstop, not the expected size of a run. The fetched query fit in 4 pages under `search_period=7`. The empty `salary` param and the `hhtmFrom` referral tags are not settings and are not sent.

`search_period=7` means a worker that was down for longer than a week never sees the gap: the site will not return those vacancies even if the checkpoint is older.

### Error handling

The collector does not raise for hh.ru fetch failures, and `CollectionService` is unchanged (Q2).

- Search page or vacancy request fails (transport error, timeout, non-success status): log it and return `CollectionResult(postings=[], invalid_entries=[])`. The checkpoint stays where it was, so the next cycle retries the same window. Successes already parsed in this run are discarded with that return; they are still newer than the checkpoint and come back next time. Do not treat this as zero vacancy ids.
- Vacancy HTML arrives but an essential field is missing: append an `InvalidEntry` (the entry dict carries the uid and the error names the field) and continue with the other vacancies. That uid is not retried once a later clean run advances the checkpoint past it. The `collect` node already writes each invalid entry to `failed_tasks`.
- A non-essential field fails to parse: keep the posting, store the default from Field mapping. No invalid entry, no drop metric.

On a run that actually returns, increment `collector_entries_dropped_total{source="headhunter", reason="parse"}` by the number of invalid entries in that result. A run discarded because a request failed increments nothing: those vacancies were not dropped, they will be retried. The helper lives next to `record_job_stage` in `monitoring/metrics.py` and swallows its own errors, same as the other recorders. `job_descriptions_total` is left as it is; its `stage` label is the pipeline funnel, and a drop is not a stage. Add the new counter to the catalogue table in `docs/architecture.md`. No Grafana panel.

### Tests

One live test, not a unit test (Q5). It calls the collector with `min_date` set to now (UTC) minus one day and asserts the run stopped on that cutoff: at least one `JobPosting`, every `posted_at` strictly newer than the cutoff, `source == "headhunter"`, uids prefixed `headhunter:`, and non-empty title, company, and description.

File: `tests/integration/test_headhunter_collector.py`. CI never collects it. The unit job is `uv run pytest tests/unit` (`.github/workflows/ci.yml:88-90`). The integration job names its files and does not include the existing live collectors (`ci.yml:127-132`; `tests/integration/test_arbeitnow_collector.py` is already in that position). Do not add this file to either list, and do not mark it `priced` — that marker is for paid calls (`tests/conftest.py:12-16`).

A local `uv run pytest` with no path arguments does collect `tests/integration/`. That is the same as Arbeitnow.

## Out of scope

- The hh.ru REST API, app tokens, and proxies.
- A real browser. The posting is in the initial HTML of both pages.
- Salary, and any new `JobPosting` field.
- Changing `CollectionService` checkpoint rules.
- Unit tests, HTML fixtures, and any edit to `.github/workflows/ci.yml`.
- Deleting the scratch fetch script and its HTML/text outputs. This feature does not read them.
- Applying to vacancies, OAuth, or areas beyond the configured search.
- A Grafana panel for the drop counter.

## Implementation phases

### Phase 1 — Collector, config, drop metric

**Depends on:** none
**Delivers:** `HeadHunterCollector` producing `JobPosting`s from search HTML and vacancy HTML, with the query defaults, the 200ms gap, the three stop conditions, the essential-field drop behaviour, and `collector_entries_dropped_total`.
**Touches:** `collection_service/headhunter_collector.py` (new), `config.py`, `monitoring/metrics.py`, `docs/architecture.md` (metric catalogue row)

### Phase 2 — Worker wiring

**Depends on:** Phase 1
**Delivers:** the collector constructed at the end of `build_collectors`, so the existing `collect` node runs it.
**Touches:** `orchestration/deps.py`, `docs/langgraph-orchestration.md` (the collector list near line 96)

### Phase 3 — Live test

**Depends on:** Phase 1
**Delivers:** a test that fetches real vacancies newer than now minus one day, and is not part of the CI unit or integration jobs.
**Touches:** `tests/integration/test_headhunter_collector.py` (new). Not `.github/workflows/ci.yml`.

## Open questions

None.

## Decision log

### Q1 — Search defaults are the query that already works

**Decided:** 2026-10-10

Keep the fetched query as the config defaults: Moscow (`area=1`), text `python разработчик`, experience `between3And6` and `moreThan6`, `employment_form=FULL`, `label=accept_labor_contract`, `accept_temporary=false`, `search_period=7`, `order_by=publication_time`, `ored_clusters=true`. One setting per param. `HH_MAX_PAGES` defaults to 10 and stays in force even when a checkpoint is present.

**Rejected:** The archived API plan's broader search (`text=python`, `area=113`, no extra filters) — that is not the query that was fetched. Dropping `search_period` — a cold start would walk whatever the site returns until the page cap, and the working query is the last 7 days.

**Consequence:** A gap longer than 7 days is invisible to the collector even when the checkpoint is older. See Config.

### Q2 — Fetch failures retry the window; unusable vacancies are dropped

**Decided:** 2026-10-10

The collector does not raise. A failed search or vacancy request returns no postings and no invalid entries, so `CollectionService` leaves the checkpoint unchanged and the next cycle retries the window. A vacancy whose essential fields cannot be read is an `InvalidEntry`, is not retried, and increments `collector_entries_dropped_total{source="headhunter", reason="parse"}`. Missing or unreadable `remote`, `location`, or `job_types` store the defaults in Field mapping and do not drop the posting.

**Rejected:** Raising — aborts the `collect` node, drops postings from collectors that already checkpointed, and skips collectors later in the list. Arbeitnow's infinite 30s retry on 429/403 — can stall the cycle for as long as hh.ru keeps refusing. Returning a partial success after a failed request — the checkpoint moves to the newest posting and the unfetched tail is skipped forever. Counting a discarded retry-the-window run as dropped — those vacancies are fetched again next cycle, so the counter would not mean "gone for good." Widening `job_descriptions_total`'s `stage` label — that series is the pipeline funnel (`monitoring/metrics.py:47`, `docs/architecture.md:189`).

**Consequence:** `CollectionService` stays as it is. Phase 2 is registration only. Permanent drops still show up as `failed_tasks` because the `collect` node already stores `invalid_entries`.

### Q3 — One request at a time, 200ms apart

**Decided:** 2026-10-10

Concurrency is 1. `HH_REQUEST_DELAY_SECONDS` defaults to `0.2`, and that delay sits between every pair of requests. A cold start of the default query is on the order of 4 search pages and about 80 vacancy pages, so the gap is most of a minute before parsing time.

**Rejected:** A few vacancy fetches in flight (the earlier lean of about 4) — faster, and more likely to trip hh.ru. No delay — the working fetch was paced by being a manual script, not by overlapping calls.

**Consequence:** `collect` blocks the rest of the cycle for the whole hh.ru walk. The other collectors run only before or after it, because `CollectionService` is sequential.

### Q4 — JSON-LD first, class names only as fallback

**Decided:** 2026-10-10

Read ids from the card `id` attribute. Read title, company, location, description, and `posted_at` from the JSON-LD `JobPosting` block. Fall back to `div.vacancy-title h1`, `span.vacancy-company-name`, and `div.vacancy-description` for title, company, and description, and to `data-qa="vacancy-address-with-map"` for location. Read `remote` and `job_types` from the `data-qa` nodes, because JSON-LD does not carry them. Description is stored as plain text.

**Rejected:** Class names as the only source — the card class suffix is a hash. Parsing `HH-Lux-InitialState` for `creationTime` — it would skip detail fetches for old vacancies, and it is a large escaped blob the working parse does not use.

**Consequence:** A vacancy with no `datePosted` is dropped (Q2). There is no other date on the vacancy page that this collector reads.

### Q5 — One live test, outside the CI unit run

**Decided:** 2026-10-10. Reopened the same day: the first decision was no tests at all. The live fetch is back; unit tests are not.

`tests/integration/test_headhunter_collector.py` calls the collector with `min_date = now(UTC) - 1 day` and checks that every returned posting is newer than that instant. See Tests for the assertions. The file is not under `tests/unit`, and it is not added to the file lists in `.github/workflows/ci.yml`, which is what keeps it off CI.

**Rejected:** No test at all — that was the first Q5 decision; a live walk to yesterday is the check that the date stop and the parse still work against hh.ru. Unit tests and trimmed HTML fixtures — the scratch pages are going away, and a unit test would run in the CI unit job (`ci.yml:90`). `@pytest.mark.priced` — that skip is for paid Apify and OpenAI calls, and hh.ru is not one of them.

**Consequence:** Phase 3 is this one file. `uv run pytest` with no arguments still collects it locally, same as `tests/integration/test_arbeitnow_collector.py`. CI does not.

### Q6 — An empty search page ends pagination

**Decided:** 2026-10-10

A search page that comes back successfully with zero vacancy ids ends the loop. That is how an out-of-range `page` behaves: HTTP 200 and no cards, not a 404. The page cap and the `min_date` stop stay as the other two exits. A request that fails is not an empty page; it follows Q2.

**Rejected:** Stopping only on an exception or on the checkpoint — with `order_by=publication_time` and a checkpoint older than the window, every page is "new" and the loop never ends. Treating the empty page as a fetch failure and discarding the run — the earlier pages were a complete newest-first prefix, and throwing them away only repeats the same walk next cycle.

**Consequence:** A block or a markup change that renders as zero cards on the first page leaves the checkpoint alone, so the next cycle retries. The same shape on a later page advances the checkpoint to the newest vacancy already collected, and anything after that page is skipped. `HH_MAX_PAGES` is what still stops the loop if a non-empty page is repeated instead of going empty.
