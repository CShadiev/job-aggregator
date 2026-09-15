# README Landing Page & Evals Showcase — Implementation Plan

**Status:** Draft
**Last updated:** 2026-09-14
**Open questions:** 8 (Q1 blocked externally — see [`screening-gate-cost-reduction-implementation-plan.md`](screening-gate-cost-reduction-implementation-plan.md))
**Origin:** Actions 1 and 3 of [`docs/flagship-demo-roadmap.md`](../flagship-demo-roadmap.md), plus a spotlight GIF of the LLM Cost & Token Accounting dashboard (a slice of action 7 pulled forward).

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done) · `Implemented` (shipped).

---

## Problem

The roadmap's assessment is that this project fails passes 1 and 2 of a reviewer's evaluation, not pass 3. Concretely, in this repository today:

- `README.md` is 306 lines of reference documentation. It opens with a one-line description and a bulleted feature list. There is no image, no badge, and no number anywhere above the fold. The repo contains **zero** image assets outside `react-app/` (which is gitignored).
- The three eval harnesses are the strongest differentiator and are invisible from the README. `benchmarks/screening/README.md` and `benchmarks/fit_assessment/README.md` are linked once each, deep inside the agent sections (`README.md:130`, `README.md:143`); `benchmarks/retrieval/` is not linked at all.
- The observability stack gets a dense metrics table (`README.md:194-208`) and no picture, even though the LLM Cost & Token Accounting dashboard is the single most on-trend artifact in the repo.

A second problem surfaced during investigation and is the reason this plan is larger than "write some markdown": **several things the README would publish are currently stale or untrue.** Surfacing them without fixing them converts a documentation gap into a credibility risk in front of exactly the audience this work targets. These are enumerated under Codebase grounding and drive Q2, Q3, Q4 and Q8.

## Scope

### In scope

- Restructure `README.md` into a landing page: hero asset, product pitch, headline numbers, badges, quick start.
- Add an `Evaluation` section to `README.md` carrying real metric tables from the screening, fit-assessment and retrieval harnesses.
- Add `docs/evals.md`: the eval loop (export → run → change → re-run) and the concrete decisions the benchmarks drove.
- Produce and embed a GIF of the **LLM Cost & Token Accounting** Grafana dashboard.
- Fix the factual defects that publishing these numbers would otherwise amplify (stale retrieval headline, missing `.env.example`, benchmark READMEs claiming datasets are tracked when they are gitignored).

### Out of scope

- Zero-credential demo mode (roadmap 2), hosted demo (4), frontend work (5), architecture case study (6), CV tailoring (8). The quick-start section is written against what exists today; see Q8.
- Improving retrieval, screening or fit-assessment *quality*. This plan publishes the numbers as they are; it does not tune the pipeline. See the note under Q2 for a product concern this surfaced.
- Changing which metrics are emitted or what the dashboards query. Restoring the local rendering path is a live question (Q6), but the panel set is fixed.
- Any change to `react-app/` — it is a separate repository (`git@github.com:cshadiev/job-aggregator-client`) and gitignored here.

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| README | `README.md` (306 lines) | Reference-style. Sections `Tech stack highlights`, `Service components`, `MongoDB collections`, `Required environment variables` are all pass-3 material sitting above anything that sells. Restructuring, not just prepending, is on the table (Q8). |
| CI badge source | `.github/workflows/ci.yml` (`CI Quality Gate`), `.github/workflows/docker-publish.yml` | Both real and green-path. CI and GHCR badges would be truthful. Note `ci.yml` has `paths-ignore: ["docs/**", "*.md"]`, so this plan's own commits will not run CI. |
| Screening eval | `benchmarks/screening/reports/20260909_115647_gpt-5.6-luna.md` (tracked) | The strong result. 300 pairs, 64.0% reduction, 192 assessment calls avoided, Good Recall 0.967, Fitting Recall 0.867, $0.1270 per 100 screenings. Run on `gpt-5.6-luna` = the production `SCREENING_MODEL`. |
| Fit-assessment eval | `benchmarks/fit_assessment/reports/20260909_173301_gpt-5.6-luna.md` (tracked) | Run on `gpt-5.6-luna`, but production `FIT_ASSESSMENT_MODEL` is `gpt-5-mini` (`config.py:112`). The published cost per 100 ($0.2317) is therefore **not** the production cost. See Q4. |
| Retrieval eval | `benchmarks/retrieval/reports/20260910_063716.md` | Headlines `K=20`, where hybrid retains 13% of fitting jobs. But production no longer uses a fixed K: `_retrieval_size()` (`orchestration/nodes/batch.py:247-249`) computes `clamp(ceil(n_jobs × PIPELINE_RETRIEVAL_RATIO), min_k, max_k)` with ratio `0.5` (`config.py:98`) — K=150 on a 300-job batch, where the same report shows hybrid at Good Recall 0.80 / Fitting Recall 0.72. The harness headline went stale at commit `cb364f2`. See Q2. |
| Retrieval reports are not committed | `.gitignore:8` ignores `benchmarks/retrieval/reports/` | Screening and fit-assessment reports are tracked; retrieval reports are not. Publishing retrieval numbers the reader cannot open is worse than not publishing them. |
| Eval datasets | `.gitignore:6-7` ignore `benchmarks/fit_assessment/dataset/01082026/` and `benchmarks/screening/dataset/05082026/` | Only `.gitkeep` is tracked. `benchmarks/screening/README.md:31` says `dataset/<DDMMYYYY>/  # git-tracked version` — untrue today. Meanwhile `benchmarks/retrieval/dataset/*/candidate.json` **is** committed and contains the author's real name, email and LinkedIn URL. The policy is inconsistent. See Q3. |
| Report templates vs. reports | `scripts/*_benchmark_report.md` | The roadmap points at these for numbers; they are `str.format` templates with `{placeholder}` fields. The real numbers live in `benchmarks/*/reports/`. |
| Retrieval and screening share a corpus | `benchmarks/retrieval/dataset/*/manifest.json` → `source.screening_dataset` | Both retrieval datasets are generated **from** `benchmarks/screening/dataset/05082026`: same 300 postings, same candidate, same gold labels. Composing the two gates is therefore a like-for-like composition, not two unrelated experiments. The versions differ only in vector mode (`text-embedding-3-small` vs `-large`). |
| The retrieval eval is credential-free | `benchmarks/retrieval/dataset/*/corpus.jsonl`, `candidate.json` | `corpus.jsonl` ships a precomputed 1536-dim `embedding` per posting and `candidate.json` ships a precomputed `query_vector` and `query_text`. `benchmarks/retrieval/test_retrieval_smoke.py:32` skips only if OpenSearch is unreachable — **no API key is needed**. This is the one eval a stranger can run today, and nothing in the README mentions it. |
| Retrieval has a regression floor, not just a report | `benchmarks/retrieval/dataset/10092026/baseline.json`, `test_retrieval_smoke.py:85-103` | The committed baseline asserts `hybrid_good_recall_at_150 ≥ 0.70` and `hybrid_fitting_recall_at_150 ≥ 0.70` in the test suite. The *test* already treats K=150 as the operating point while the *markdown report* still headlines K=20 — internal confirmation that the report, not the system, is stale. |
| `corpus.jsonl` dominates repo weight | 12 MB × 2 versions | Roughly 24 MB of the 27 MB `.git` is committed eval corpora. Precedent for committing large artifacts already exists; relevant to Q7. |
| LLM cost dashboard | `monitoring/grafana/dashboards/llm-cost-accounting.json` | 7 panels: 24h spend, 24h tokens, cost per pipeline cycle, tokens per assessed pair, daily burn by agent, prompt-vs-completion donut, per-agent/model efficiency table. Good GIF material — the variables (`$agent`, `$model`) give it something to *do* on screen. |
| Local Grafana is broken | commit `e03d659` | That commit replaced the v1 dashboards with Grafana Cloud v2-schema exports (`apiVersion: dashboard.grafana.app/v2`, datasource `grafanacloud-cshadiev-prom`) and **deleted** `monitoring/grafana/provisioning/{datasources,dashboards}/*.yml` and `monitoring/prometheus/prometheus.yml`. `docker-compose.yml:152,176` still mounts the deleted paths. `docker compose up -d` cannot bring up a working Prometheus/Grafana today. See Q6. |
| Cost model | `monitoring/pricing.py:34-40` | `DEFAULT_RATES`: `gpt-5.6-luna` $0.20/$1.20 per 1M in/out, `gpt-5-mini` $0.25/$2.00. Any headline cost claim is reproducible from these plus the token counts in the reports. |
| Missing `.env.example` | `README.md:248` says `cp .env.example .env` | The file does not exist. The first command in the quick start fails. |
| Frontend | `react-app/` (gitignored, separate repo) | Job feed table with fit scores, filters, status editor, cover-letter modal (`react-app/src/pages/jobs/`). There is no fit-assessment detail view and no pipeline dashboard — those are roadmap 5. Constrains what a hero GIF can show (Q5). |
| Repo weight | `.git` is 27 MB | Committed GIFs are permanent history. A 20-second dashboard GIF is typically 3–15 MB. See Q7. |

### The headline arithmetic, as it actually computes

The roadmap asks for one sentence: *"the screening gate drops X% of pairs before assessment, cutting cost per run by Y% at Z% recall."* Derived from the committed reports and `DEFAULT_RATES`, on a 300-pair batch for one candidate:

| Path | Cost | Top-tier retention |
| --- | --- | --- |
| Assess every pair (`gpt-5-mini`, 9290 in / 383 out per call) | $0.926 | 1.00 |
| Screen first (`gpt-5.6-luna`), assess the 108 survivors | $0.381 + $0.334 = **$0.715** | 0.967 |

That is a **23%** saving, not the order-of-magnitude cut the phrase "cost-gating architecture" implies. The large lever is the *retrieval* gate ahead of it: at the production ratio of 0.5 it halves the pair count before any LLM runs. Composing both gates on the same 300-job corpus gives 150 retrieved → 54 assessed → **$0.357**, a 61% cut at a compounded top-tier retention of 0.80 × 0.967 ≈ 0.77.

The second number is the better story and the softer evidence, though less soft than it first appears: the retrieval and screening benchmarks run on the *same* 300 postings for the same candidate (`10092026` is generated from `screening/dataset/05082026`), so composing their gates is legitimate. Two caveats remain. The fit-assessment cost is transposed to `gpt-5-mini` rates the benchmark never paid (Q4), and the composition assumes screening's 64% drop rate carries over to the top-150 retrieved subset — a pre-filtered, higher-quality distribution where it will almost certainly be lower. Q1 is which number goes above the fold and how the assumption is labelled.

> **Superseded in part — see [`screening-gate-cost-reduction-implementation-plan.md`](screening-gate-cost-reduction-implementation-plan.md).** Production telemetry has since contradicted both of the caveats above. On the last cycle 300 pairs were screened for $0.41 and 145 survivors assessed for $0.34, totalling $0.75 against ~$0.70 to assess all 300 outright — so the deployed single-gate saving is **−6.6%**, not +23%. The drop rate on the post-retrieval subset is 51.7%, not 64%, which is the "almost certainly lower" caveat measured rather than predicted, and it drags the composed number down too. The governing identity is `saving = r − ρ` (reduction rate minus the screening-to-assessment cost ratio); the gate broke even at ρ = r and currently sits the wrong side of it, because commit `f854085` moved assessment off `grok-4.3` and made the work being avoided 11× cheaper. **Q1 should not be decided until that plan's packaging and model work lands** — there is currently no positive single-gate number to publish. Nothing in this section is deleted, since the arithmetic itself is still correct for the committed reports.

## Design

### README structure

Depends on Q5 (hero), Q7 (asset location) and Q8 (split and quick-start promise). The intended order of the landing section, independent of those:

1. Title, one-sentence positioning line, badge row (CI, GHCR, Python 3.13, licence if one is added).
2. Hero asset.
3. Three-line pitch, product-framed rather than pipeline-framed.
4. Headline numbers — three or four figures, each a link to the report it came from (Q1).
5. Quick start (Q8).
6. Architecture diagram — the existing Mermaid flowchart at `README.md:42-69` already earns its place here.

Everything from `## Service components` down is reference material; whether it stays in `README.md` or moves is Q8.

### Evaluation section

Depends on Q1, Q2, Q3, Q4. Structure, once those close:

- One paragraph on why a gate benchmark is not a classifier benchmark: every harness reports *Reduction Rate* and *recall against gold bands*, because the question is "how much downstream spend did this remove, and what did it cost in good candidates", not "what is the F1".
- One table per harness — screening, fit assessment, retrieval — at the production operating point, each linking to the committed report.
- The cost/accuracy sentence from Q1.
- One line on the regression floor: `benchmarks/retrieval/test_retrieval_smoke.py` fails CI if hybrid recall at K=150 drops below the committed `baseline.json`. "We measured it once" and "it cannot silently regress" are different claims, and only the second one is an engineering practice.
- A link to `docs/evals.md`.

Each table must state its operating point explicitly (`t=0.0` for screening, `cv_ats_match_score >= 80` for fit assessment, `K` for retrieval) because all three harnesses also publish sweeps, and a number lifted out of a sweep without its threshold is meaningless.

### `docs/evals.md`

The loop, using the real entry points: `scripts/export_screening_benchmark_dataset.py` → `uv run run-screening-benchmark` → report under `benchmarks/screening/reports/` → prompt or model change → re-run. Same shape for the other two, noting that retrieval regenerates from an existing screening dataset (`benchmarks/retrieval/dataset/10092026/manifest.json` records `source.screening_dataset`), which is also why the two can be composed into one end-to-end number (Q1).

This is also the right place to document the two-tier structure the harnesses already have but never explain: a **benchmark** you run deliberately when changing a prompt or a model, and a **frozen regression floor** (`baseline.json` + `test_retrieval_smoke.py`) that runs in CI and blocks a merge. The second tier only exists for retrieval today; whether screening and fit assessment should get one is worth a sentence, not a silent omission.

The part worth writing carefully is *what the benchmarks decided*. Candidates visible in the history, to be confirmed with the user rather than asserted:

- Screening runs `gpt-5.6-luna` while fit assessment runs `gpt-5-mini` — a model split the harnesses should be able to justify.
- Production screening ignores the confidence score. The sweep supports this directly: confidence clusters at mean 0.946 and cutoffs below 0.9 move nothing (`20260909_115647` sweep rows for t=0.5–0.8).
- The pair gate moved from a fixed top-K to a ratio of the batch (`cb364f2`).

`docs/evals.md` is also where the honest caveats live (dataset is one candidate, gold labels are historical production assessments rather than independent human labels) — pushed here rather than into the README so the landing page stays readable, but not omitted.

### Dashboard spotlight

Depends on Q6 (how it is produced) and Q7 (where it lives). The recording itself, once a renderable dashboard exists: a ~15–20 second loop over the LLM Cost & Token Accounting dashboard, starting on the four stat panels, scrolling to the burn-rate timeseries and the prompt/completion donut, ending on the per-agent/model efficiency table, with one `$agent` variable change mid-way to show it is a live dashboard and not a screenshot.

Placement is decided: inside the Evaluation section, under a subheading that ties it to the offline numbers — the benchmarks prove the gates work on a fixed dataset, the dashboard proves the same spend is tracked per agent and per model in production. Written that way it strengthens action 3 rather than being a stray ops screenshot.

### Correctness fixes

In scope because publishing the numbers without them is the risk, not the documentation gap:

- `.env.example` with every variable from `README.md:276-289` plus the optional tuning list at `README.md:291`, values blanked.
- `benchmarks/screening/README.md:31` and the equivalent line in `benchmarks/fit_assessment/README.md` — reconcile with whatever Q3 decides.
- `benchmarks/screening/README.md:8` links to `docs/planning/screening-agent.md`, which moved to `docs/planning/archive/` in commit `57a4f47`. Broken link; the equivalent line in `benchmarks/fit_assessment/README.md` needs the same check.
- The retrieval report headline (`scripts/run_retrieval_benchmark.py:153-163` hardcodes `@20`) — reconcile with whatever Q2 decides.

## Open questions

### Q1 — Which cost/accuracy claim goes above the fold, and how is it derived?

**Blocks:** README headline numbers, the Evaluation section's closing sentence, `docs/evals.md`.
**Blocked by:** [`screening-gate-cost-reduction-implementation-plan.md`](screening-gate-cost-reduction-implementation-plan.md). The measured single-gate saving in production is −6.6%, and the composed estimate's key assumption (that screening's 64% drop rate survives the retrieval pre-filter) is measured at 51.7% in production. Both numbers below are therefore stale as *production* claims, though still accurate as claims about the committed reports. That plan's Q5 covers whether the harness reports the full-corpus or post-retrieval operating point, which decides which r this question can use.
**Context:** See "The headline arithmetic" above. The measured single-gate claim is 23% and fully defensible from one committed report. The composed two-gate claim is 61% but assumes screening's drop rate holds on the retrieved subset. Option (c) is cheaper than it looks: retrieval and screening already share corpus `05082026`, and `benchmarks/screening/reports/*.results.jsonl` carries a per-`job_uid` prediction for all 300 postings. Intersecting the retrieval top-K uid list with those predictions measures the composition exactly, with **zero new LLM calls** — the only missing piece is that `run_retrieval_benchmark.py` writes aggregate metrics and never persists the ranked uid list, so it would have to emit one (OpenSearch and the committed embeddings are all it needs).
**Options:** (a) publish the measured screening-gate number only; (b) publish the composed end-to-end estimate, labelled as such, with the derivation in `docs/evals.md`; (c) make the composed number measured — have the retrieval harness emit ranked uids, replay the stored screening predictions over the top-K set, and report the real compounded reduction and recall.
**Leaning:** (c), having found the results file makes it nearly free. It turns the headline from an estimate a reviewer must trust into a number they can recompute, and it is the one claim that describes the architecture the project is actually selling. Fall back to (b) if emitting the uid list turns out to require re-embedding the corpus.

### Q2 — How is retrieval published, given the report headlines an operating point production abandoned?

**Blocks:** the retrieval row of the Evaluation section; `scripts/run_retrieval_benchmark.py`.
**Context:** `_KS = (20, 50, 90, 100, 150)` and `_format_markdown_report` hardcodes the `@20` headline, but production runs `PIPELINE_RETRIEVAL_RATIO=0.5` → K=150 on this corpus. At K=20 hybrid keeps 13% of fitting jobs; at K=150 it keeps 72% (Good 0.80) against a 50% naive baseline. The K=150 rows are already in the committed sweep, so re-headlining needs **no re-run** — but the JSON the report is rendered from is gitignored, so it would have to be regenerated locally or un-ignored.
**Options:** (a) re-headline the harness to the production operating point and commit the regenerated report; (b) leave the harness alone and quote the K=150 sweep row in the README with a footnote; (c) omit retrieval from the README and keep it in `docs/evals.md`.
**Leaning:** (a), plus un-ignoring `benchmarks/retrieval/reports/` so the published numbers are checkable. It is a small change to one formatter, and it fixes a report that currently misdescribes production to anyone who opens it — independent of whether the number is ever published. `benchmarks/retrieval/dataset/10092026/baseline.json` already pins the regression floor at `*_at_150`, so the repo has in effect already made this decision everywhere except the report header.
**Flagged, not in scope:** if the *intent* was ever a tight top-K gate, the retrieval evidence says a tight gate is not viable — hybrid at K=20 retains barely twice the random baseline. The ratio of 0.5 is doing the right thing for the wrong-looking reason, and the harness never told anyone. That is a product question for a separate plan.

### Q3 — Do the eval datasets become reproducible, and at what privacy cost?

**Blocks:** `docs/evals.md` reproducibility claims; the wording of every "run it yourself" line in the Evaluation section; `benchmarks/*/README.md` corrections.
**Context:** `benchmarks/screening/dataset/05082026/` and `benchmarks/fit_assessment/dataset/01082026/` are gitignored and contain `cv.pdf` — a real CV — alongside `entries.jsonl` (job text plus gold labels). Their READMEs claim the datasets are tracked. Meanwhile `benchmarks/retrieval/dataset/*/candidate.json` **is** committed with the author's real name, email and LinkedIn. So the repo is simultaneously stricter and looser than it thinks. Without a committed dataset, `uv run run-screening-benchmark` cannot be run by a reader — while the retrieval eval next door runs with no credentials at all (see Q8). Publishing three harnesses where one is reproducible and two are not is a worse look than publishing three where the boundary is stated.
**Options:** (a) commit `entries.jsonl` + `manifest.json` and keep `cv.pdf` out, documenting the harness as runnable only with your own CV; (b) commit a synthetic CV and re-export gold labels against it — reproducible, but the labels would no longer be the production assessments they claim to be; (c) commit everything including the CV, accepting that it is the author's own public CV, consistent with what `candidate.json` already exposes; (d) commit nothing and state plainly in `docs/evals.md` that datasets are private.
**Leaning:** (c) or (a). The CV is the author's own and its contents are already on a public website linked from `candidate.json`; (c) makes the harness genuinely runnable, which is the whole point. (a) is the conservative version. (b) is the worst of both — effort spent to weaken the labels.

### Q4 — Is the fit-assessment benchmark re-run on the production model before its numbers are published?

**Blocks:** the fit-assessment row of the Evaluation section; the cost input to Q1.
**Context:** The committed report ran `gpt-5.6-luna`; production assessment is `gpt-5-mini` (`config.py:112`). Publishing $0.2317 per 100 as the assessment cost would be publishing a number from a model the pipeline does not use. Re-running is 100 calls — roughly $0.31 at `gpt-5-mini` rates and a few minutes at concurrency 10. It also produces a second data point on model choice, which is directly useful for the `docs/evals.md` "what the benchmarks decided" section. The catch: it requires the gitignored dataset, so it can only be done on your machine, and a materially different result would reopen Q1's arithmetic.
**Options:** (a) re-run on `gpt-5-mini` and publish that; (b) publish the `gpt-5.6-luna` numbers with the model stated and the cost transposed arithmetically; (c) re-run and publish both, as the model-selection evidence.
**Leaning:** (c). The cost is trivial and a two-model comparison table is exactly the artifact that makes the eval loop look real rather than ceremonial.

### Q5 — What is the hero asset above the fold?

**Blocks:** the top of `README.md`; the recording work in Phase 3.
**Context:** The roadmap asks for a job-feed GIF with fit scores and a generated cover letter. That UI exists (`react-app/src/pages/jobs/`) but lives in a separate repository and is gitignored here, and it cannot run without Mongo, OpenSearch, S3, Auth0 and real scraped data — demo mode (roadmap 2) is what would fix that, and it is not in this plan. So the hero must be recorded from your working instance either way; the question is what it shows.
**Options:** (a) the UI job feed → cover-letter modal, the most product-like and the most obviously "not in this repo"; (b) a terminal recording of `uv run run-pipeline` with structured logs streaming through collect → normalize → dedupe → screen → assess → cover_letter, which is entirely this repo's code and reinforces the pipeline positioning; (c) a static composite image of two or three screenshots, cheapest and lowest impact; (d) the LLM cost dashboard as hero, moving the spotlight to the top.
**Leaning:** (a) with an explicit link to the client repo in the same block. A reviewer's first 30 seconds should show a product, and the pipeline GIF (b) is a better *second* asset than a first one. Worth noting (a) and (b) are not exclusive if the recording session is happening anyway.

### Q6 — How is the dashboard GIF produced, and does restoring the local observability stack come into scope?

**Blocks:** the spotlight subsection; Phase 3; possibly `monitoring/` and `docker-compose.yml`.
**Context:** Commit `e03d659` deleted `monitoring/prometheus/prometheus.yml` and `monitoring/grafana/provisioning/**` and replaced the v1 dashboards with Grafana Cloud v2-schema exports pointing at `grafanacloud-cshadiev-prom`. `docker-compose.yml` still mounts all three deleted paths. So today the only place any dashboard renders is your Grafana Cloud org. The deleted files are recoverable verbatim (`git show e03d659^:monitoring/prometheus/prometheus.yml`), but the dashboards are no longer in a schema local Grafana 12.2 provisions, and even restored, a local stack has no metrics until a pipeline run produces some.
**Options:** (a) record from Grafana Cloud against real pipeline data — fastest, needs no code change, but the dashboard in the repo remains un-renderable by any reader and the GIF may show the org name; (b) restore provisioning, convert the three dashboards back to a locally-provisionable schema with a local datasource uid, and record locally against a real `run-pipeline` cycle — fixes `docker compose up` as a side effect and makes "dashboards as code" true again, at the cost of a dashboard-schema round trip and keeping two variants in sync; (c) as (b) but feed the local Prometheus synthetic data from a seed script so the GIF is reproducible without spending on LLM calls; (d) publish a Grafana public-dashboard link instead of a GIF — interactive and zero maintenance until the Cloud instance lapses.
**Leaning:** (b). The repo currently claims dashboards-as-code while shipping a stack that cannot start; this is the cheapest moment to fix that, and the fix is worth more than the GIF. (a) is the pragmatic fallback if the schema conversion turns ugly. (c) adds a synthetic-data generator this plan does not otherwise need — reconsider it only if you want the GIF re-recordable later.

### Q7 — Where do binary assets live?

**Blocks:** every embed in `README.md` and `docs/evals.md`.
**Context:** `.git` is 27 MB and contains no images. GIFs at the length described run 3–15 MB each, and this plan produces at least two. Git history is append-only, so this choice is effectively permanent; re-recording a hero GIF three times means carrying all three forever.
**Options:** (a) commit under `docs/assets/`, self-contained and works on any mirror; (b) attach to a GitHub release or an issue and embed the CDN URL, zero repo weight but the README breaks if the object is removed and it does not render offline; (c) commit stills, link out to a hosted video.
**Leaning:** (a) for stills unconditionally, (b) for GIFs above ~5 MB. Worth pairing with a size budget — a GIF that has been cropped and frame-capped to under 5 MB is also a GIF that loads before the reader scrolls past it.

### Q8 — Does the README split, and what does the quick start promise?

**Blocks:** the overall shape of `README.md`; whether `docs/architecture.md` is created.
**Context:** The current 306 lines are genuinely good reference material — the collections table, the metrics table, the env var table. A landing page needs its first screen to sell; the two goals compete directly. Separately, the first command of the current quick start is `cp .env.example .env` and that file does not exist, and even with it, a reader needs Apify, OpenAI, Grok, Auth0 and S3 credentials to get anywhere. Demo mode (roadmap 2) is the real answer and is out of scope here, so this plan has to decide what to promise in the meantime.
**Options for the split:** (a) prepend the landing section, keep everything else — one file, gets long; (b) move `Service components`, `MongoDB collections`, env vars and the observability table into `docs/architecture.md`, leaving a README of roughly 120 lines — sharper, and gives roadmap 6 (case study) somewhere to land, at the cost of a doc that must be kept in sync; (c) split by audience into `docs/architecture.md` plus `docs/operations.md`.
**Options for the quick start:** (i) `.env.example` plus honest "requires five external services" framing, with a placeholder noting demo mode is coming; (ii) lead with what *does* run credential-free today, then the credentialled path below it; (iii) omit the quick start until demo mode ships.
**Leaning:** (b) and (ii). A "Try it in 2 minutes" block that cannot deliver two minutes is worse than no block — but a real two-minute path already exists and nobody knows about it. `docker compose up -d opensearch` plus `uv run pytest benchmarks/retrieval/` runs the hybrid retrieval eval against the committed corpus with **no API keys**, because the embeddings and the candidate query vector are committed alongside it. A quick start that opens with "clone, one container, and you can re-run our retrieval benchmark" is the strongest 2-minute story available before demo mode ships, and it lands squarely on this plan's theme rather than working around it.

## Decision log

Empty. Questions move here with their IDs when resolved.

## Suggested question sequence

1. **Q1 and Q4 together.** Q1 is the spine of both README and `docs/evals.md`, and Q4 changes Q1's inputs — deciding Q1 first and then re-running on `gpt-5-mini` would mean redoing the arithmetic. Q4 is nearly free; settle it, run it if yes, then fix Q1 against real numbers.
2. **Q2 and Q3.** Both are "what do we publish and can a reader check it", both touch the harnesses rather than the README, and both are independent of the visual work. Batchable in one session.
3. **Q8.** Structure decides where everything from steps 1–2 lands. Cheap to decide, expensive to change after the prose is written.
4. **Q6.** The largest implementation variance in the plan, from "record a screen" to "restore and convert the observability stack". Worth its own session, and it can proceed in parallel with the writing.
5. **Q5 and Q7.** Both gate the recording session only. Decide them together right before Phase 3 so the hero and the spotlight are captured in one sitting at one size budget.

## Implementation phases

Skeletal until the questions close.

### Phase 1 — Harness and repo truthfulness

**Depends on:** Q2, Q3, Q4
**Reviewable when:** the committed reports and benchmark READMEs describe the pipeline that actually runs, and `cp .env.example .env` works.
**Touches:** `scripts/run_retrieval_benchmark.py`, `.gitignore`, `benchmarks/*/README.md`, `benchmarks/*/reports/`, `.env.example`

### Phase 1b — Composed gate measurement

**Depends on:** Phase 1, and only exists if Q1 lands on (c)
**Reviewable when:** a committed report states the compounded reduction rate and good/fitting recall of retrieval + screening over corpus `05082026`, reproducible from the committed corpus and the stored screening predictions without any LLM call.
**Touches:** `scripts/run_retrieval_benchmark.py` (emit ranked uids), a new composition step, `benchmarks/retrieval/reports/`

### Phase 2 — Evaluation content

**Depends on:** Phase 1 (and 1b if it exists), Q1, Q8
**Reviewable when:** `docs/evals.md` and the README Evaluation section exist, every number links to the report it came from, and every table states its operating point.
**Touches:** `docs/evals.md`, `README.md`

### Phase 3 — Assets

**Depends on:** Q5, Q6, Q7 (independent of Phases 1–2)
**Reviewable when:** the hero asset and the dashboard GIF exist at their agreed sizes and locations; if Q6 lands on (b) or (c), `docker compose up -d` additionally brings up a Grafana that renders the three dashboards.
**Touches:** `docs/assets/` (per Q7), and per Q6 possibly `monitoring/grafana/provisioning/`, `monitoring/grafana/dashboards/*.json`, `monitoring/prometheus/prometheus.yml`

### Phase 4 — README landing page

**Depends on:** Phases 2 and 3, Q8
**Reviewable when:** the first screen carries pitch, badges, hero and headline numbers, and nothing above the fold is unverifiable.
**Touches:** `README.md`, `docs/architecture.md` (per Q8)
