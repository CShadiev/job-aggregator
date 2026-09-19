# README Landing Page & Evals Showcase — Implementation Plan

**Status:** Ready for implementation
**Last updated:** 2026-09-15
**Open questions:** 0
**Origin:** Actions 1 and 3 of [`docs/flagship-demo-roadmap.md`](../flagship-demo-roadmap.md), plus a spotlight GIF of the LLM Cost & Token Accounting dashboard (a slice of action 7 pulled forward).

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done) · `Implemented` (shipped).

---

## Problem

The roadmap's assessment is that this project fails passes 1 and 2 of a reviewer's evaluation, not pass 3. Concretely, in this repository today:

- `README.md` is 306 lines of reference documentation. It opens with a one-line description and a bulleted feature list. There is no image, no badge, and no number anywhere above the fold. The repo contains **zero** image assets outside `react-app/` (which is gitignored).
- The three eval harnesses are the strongest differentiator and are invisible from the README. `benchmarks/screening/README.md` and `benchmarks/fit_assessment/README.md` are linked once each, deep inside the agent sections (`README.md:130`, `README.md:143`); `benchmarks/retrieval/` is not linked at all.
- The observability stack gets a dense metrics table (`README.md:194-208`) and no picture, even though the LLM Cost & Token Accounting dashboard is the single most on-trend artifact in the repo.

Pass 2 is a different shape than the roadmap assumed. A fully working instance has been running for weeks and updates from `main` almost as soon as commits land, so the reviewer-facing answer is a live demo rather than a local quick start (Q5, Q8). What is still missing is the README treating that instance as the product: no hero of it, no headline numbers next to it. The hero GIF is the no-login preview; a URL is secondary with no promise a stranger can sign in (Q10).

A second problem surfaced during investigation and is the reason this plan is larger than "write some markdown": **several things the README would publish are currently stale or untrue.** Surfacing them without fixing them converts a documentation gap into a credibility risk in front of exactly the audience this work targets. These are enumerated under Codebase grounding and drive the correctness work in Phase 1 (Q2, Q3, Q4).

## Scope

### In scope

- Restructure `README.md` into a landing page: hero asset, product pitch, headline numbers, badges. A live-instance URL may appear as a secondary link with no login promise (Q8, Q10). Reference material moves to `docs/architecture.md`.
- Add an `Evaluation` section to `README.md` carrying real metric tables from the screening, fit-assessment and retrieval harnesses, each linking to a committed report.
- Add `docs/evals.md`: the eval loop (export → run → change → re-run) as a **maintainer** loop, the concrete decisions the benchmarks drove, and a plain statement that datasets are private and results are public (Q3).
- Produce and embed a GIF of the **LLM Cost & Token Accounting** Grafana dashboard, recorded from Grafana Cloud (Q6).
- Produce and embed a hero GIF of the live UI (job feed → cover-letter modal); optionally a second terminal GIF of `uv run run-pipeline` (Q5).
- Fix the factual defects that publishing these numbers would otherwise amplify: stale retrieval headline (Q2), benchmark READMEs vs. gitignore, fit-assessment/cover-letter `config.py` defaults still on `gpt-5-mini` while the live env runs luna (Q4), missing `.env.example` as operator documentation in `docs/architecture.md`.
- Flip artifact policy: untrack eval datasets (including the currently committed retrieval corpora), commit all harness reports (Q3). Measure the composed retrieval+screening number and commit it (Q1). Rewrite the retrieval CI floor to assert that committed ranked-uid list against `baseline.json` instead of re-indexing the corpus (Q9).

### Out of scope

- Zero-credential local demo mode (roadmap 2), frontend feature work (roadmap 5), architecture case study as a standalone essay (roadmap 6 — `docs/architecture.md` is only the README split), CV tailoring (roadmap 8).
- Building a new hosted demo or a demo-account / "sign in as demo" flow (Q10). The instance already exists; the GIF is the reviewer preview.
- A reviewer-facing quick start. Too many external dependencies; nobody will run this locally (Q8).
- Improving retrieval, screening or fit-assessment *quality*. This plan publishes the numbers as they are; it does not tune the pipeline.
- Changing which metrics are emitted or what the dashboards query. Restoring local Grafana provisioning is **not** in this plan (Q6); the broken `docker compose` mounts stay as they are.
- Any change to `react-app/` — it is a separate repository (`git@github.com:cshadiev/job-aggregator-client`) and gitignored here. The hero is recorded from the running instance, not built in this repo.
- Rewriting git history to purge already-committed retrieval corpora or `candidate.json` PII. Untracking going forward does not unpublish history.

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| README | `README.md` (306 lines) | Reference-style. Sections `Tech stack highlights`, `Service components`, `MongoDB collections`, `Required environment variables` are pass-3 material sitting above anything that sells. Q8 moves them to `docs/architecture.md`. |
| CI badge source | `.github/workflows/ci.yml` (`CI Quality Gate`), `.github/workflows/docker-publish.yml` | Both real and green-path. CI and GHCR badges would be truthful. Note `ci.yml` has `paths-ignore: ["docs/**", "*.md"]`, so this plan's own commits will not run CI. |
| Live instance | `config.py:139` `ALLOWED_ORIGINS = ["https://cshadiev.dev"]`; deploys from `main` | Recording source for Q5. README may link it secondarily; the hero GIF is the no-login preview (Q10). |
| Screening eval | `benchmarks/screening/reports/` (tracked, including the 2026-09-15 packaging/bake-off runs) | Strongest committed artifact. Latest luna run is `20260915_125405_gpt-5.6-luna.md`; bake-off winner is `glm-5.3-flash` (`20260915_130230`). Live env still runs luna — the glm switch has not been deployed yet (Q4). README numbers follow what's running; `config.py` keeps the glm default as the decided next screening model. |
| Fit-assessment eval | `benchmarks/fit_assessment/reports/20260909_173301_gpt-5.6-luna.md` (tracked) | Run on `gpt-5.6-luna`. Live env sets `FIT_ASSESSMENT_MODEL` (and `COVER_LETTER_MODEL`) to luna, so the report **is** production-relevant. `config.py:113-114` still default to `gpt-5-mini` with no pending model switch — those two defaults are the lie to fix (Q4). |
| Retrieval eval | `benchmarks/retrieval/reports/` currently **gitignored**; formatter hardcodes `@20` | Production uses `PIPELINE_RETRIEVAL_RATIO=0.5` → K=150 on this corpus. Re-headline and commit the report (Q2). Un-ignore `reports/` as part of publishing all results (Q3). |
| Eval datasets | `.gitignore:6-10` ignore screening/fit-assessment dataset dirs (screening keeps `baseline.json`); retrieval datasets **are committed** | `benchmarks/retrieval/dataset/*/candidate.json` contains the author's name, email and LinkedIn. Q3 makes **all** datasets private and **all** results public — retrieval corpora get the screening treatment, retrieval reports get the screening treatment in reverse. |
| Retrieval CI today re-runs search | `benchmarks/retrieval/test_retrieval_smoke.py:21-51`, `.github/workflows/ci.yml:166-170` | Loads `dataset/05082026` and re-indexes into CI OpenSearch. After untracking, that cannot run on GitHub. Q9: drop the OpenSearch re-run from CI; assert the committed ranked-uid list against `baseline.json`. Keep `tests/integration/test_search_service.py` on the OpenSearch job. |
| Report templates vs. reports | `scripts/*_benchmark_report.md` | The roadmap points at these for numbers; they are `str.format` templates with `{placeholder}` fields. The real numbers live in `benchmarks/*/reports/`. |
| Retrieval and screening share a corpus | `benchmarks/retrieval/dataset/*/manifest.json` → `source.screening_dataset` | Both retrieval datasets are generated **from** `benchmarks/screening/dataset/05082026`: same 300 postings, same candidate, same gold labels. Composing the two gates is like-for-like. Q1 measures that composition from stored screening predictions plus a ranked-uid list the retrieval harness does not yet emit. |
| Screening predictions are already public | `benchmarks/screening/reports/*.results.jsonl` | Per-`job_uid` predictions for all 300 postings. Intersecting them with a committed ranked-uid list needs **zero new LLM calls** and does not require the dataset to be public. |
| Retrieval regression floor | `benchmarks/retrieval/dataset/10092026/baseline.json` (and `05082026/baseline.json`) | Asserts hybrid recall at K=150. After Q3, `baseline.json` stays committed; the corpus does not. After Q9, CI checks the ranked-uid artifact against this file rather than re-searching. Pin whichever dataset version the committed ranked-uid list was generated from. |
| `corpus.jsonl` dominates repo weight | 12 MB × 2 versions, already in git history | Untracking does not shrink `.git`. Relevant to Q3 and Q7 only as "the weight is already paid". |
| LLM cost dashboard | `monitoring/grafana/dashboards/llm-cost-accounting.json` | 7 panels: 24h spend, 24h tokens, cost per pipeline cycle, tokens per assessed pair, daily burn by agent, prompt-vs-completion donut, per-agent/model efficiency table. Spotlight GIF recorded from Grafana Cloud (Q6), committed under `docs/assets/` (Q7). |
| Local Grafana is broken | commit `e03d659` | v2-schema Cloud exports; deleted provisioning files; `docker-compose.yml` still mounts them. Q6 leaves this alone. Operator docs should not claim `docker compose up -d` brings up Grafana. |
| Cost model | `monitoring/pricing.py` | `DEFAULT_RATES` include `gpt-5.6-luna` and `glm-5.3-flash`. Headline cost claims are reproducible from these plus token counts in the reports. |
| Missing `.env.example` | `README.md:248` says `cp .env.example .env` | File does not exist. After Q8 this command leaves the landing page; it still belongs in `docs/architecture.md` as operator setup. |
| Model defaults vs live env | `config.py:111-114` | `SCREENING_MODEL` default is `glm-5.3-flash` (bake-off winner; not deployed yet). `FIT_ASSESSMENT_MODEL` and `COVER_LETTER_MODEL` default to `gpt-5-mini` while the live env runs luna on all three. README:293 documents the defaults, not the env. Q4: do not revert screening to luna; do align the two mini defaults. |
| Frontend | `react-app/` (gitignored, separate repo) | Job feed with fit scores, filters, status editor, cover-letter modal. Hero is recorded from the live instance (Q5), not from a local checkout of this repo. |
| Repo weight | `.git` is 27 MB | Q7 commits GIFs under `docs/assets/`. History is append-only. |

### The headline arithmetic, as it actually computes

The roadmap asks for one sentence: *"the screening gate drops X% of pairs before assessment, cutting cost per run by Y% at Z% recall."* The number that goes above the fold is **the measured composition of retrieval + screening** on corpus `05082026` (Q1), not a single-gate screening figure and not an estimate that assumes screening's full-corpus drop rate on the retrieved subset.

Historical arithmetic on the original committed reports (kept so the derivation is auditable, not as the headline):

| Path | Cost | Top-tier retention |
| --- | --- | --- |
| Assess every pair (`gpt-5-mini`, 9290 in / 383 out per call) | $0.926 | 1.00 |
| Screen first (`gpt-5.6-luna`), assess the 108 survivors | $0.381 + $0.334 = **$0.715** | 0.967 |

That is a **23%** saving on screening alone. Composing with retrieval at ratio 0.5 *as an estimate* gave 150 retrieved → 54 assessed → **$0.357**, a 61% cut at compounded retention ≈ 0.77 — but that assumed screening's 64% drop rate on the top-150 subset.

> **Superseded as a publishable claim — see [`screening-gate-cost-reduction-implementation-plan.md`](screening-gate-cost-reduction-implementation-plan.md) (Implemented).** Production telemetry then showed a **−6.6%** single-gate saving (drop rate 51.7% post-retrieval, ρ > r after assessment moved off `grok-4.3`). Packaging and a model bake-off have since landed; the identity `saving = r − ρ` still governs. Q4: live assessment is still `gpt-5.6-luna` (not the `gpt-5-mini` rates above), and live screening is still luna because the glm switch has not been deployed. **Do not publish the 23% or 61% figures.** Phase 1b produces the composed number from stored screening predictions plus a newly emitted ranked-uid list, using the luna screening results that match what is running today.

The composition is legitimate on corpus grounds: retrieval `10092026` / `05082026` are generated from `screening/dataset/05082026`. After Q3 the datasets stay private; the ranked-uid list and the screening `.results.jsonl` are public, so a reader can recompute the composition without the corpus. After Q9 that same ranked-uid list is what CI asserts against `baseline.json`.

## Design

### README structure

Intended order of the landing section:

1. Title, one-sentence positioning line, badge row (CI, GHCR, Python 3.13, licence if one is added).
2. Hero asset — UI job feed → cover-letter modal, recorded from the live instance. Link the client repo in the same block. This is the no-login preview (Q10).
3. Three-line pitch, product-framed rather than pipeline-framed.
4. Headline numbers — three or four figures, each a link to the report it came from, including the measured composed gate number from Phase 1b.
5. Architecture diagram — the existing Mermaid flowchart at `README.md:42-69` already earns its place here.
6. Optional quiet link to the live instance (`https://cshadiev.dev` or whatever URL is current), framed as the author's running deployment, not as "try it". No demo credentials.

No quick start on the landing page (Q8). Operator setup (`uv sync`, `.env.example`, compose) lives in `docs/architecture.md` with the collections table, env-var table, metrics table and service-component notes currently in `README.md`. That operator doc must not claim a working local Grafana stack (Q6).

Optional second visual: a terminal recording of `uv run run-pipeline` (Q5), placed with the architecture diagram rather than above the fold.

### Evaluation section

Structure:

- One paragraph on why a gate benchmark is not a classifier benchmark: every harness reports *Reduction Rate* and *recall against gold bands*, because the question is "how much downstream spend did this remove, and what did it cost in good candidates", not "what is the F1".
- One table per harness — screening, fit assessment, retrieval — at the production operating point, each linking to the committed report. Retrieval headlines K=150 (Q2). Models stated as `gpt-5.6-luna` because that is what the live env runs today (Q4); screening's glm bake-off belongs in `docs/evals.md` until the switch lands.
- The measured composed retrieval+screening sentence from Phase 1b (Q1).
- One line on the regression floor: CI asserts the committed ranked-uid list against `baseline.json` (Q9). "We measured it once" and "it cannot silently regress" remain different claims; the second one now runs on a public artifact instead of a private corpus.
- A link to `docs/evals.md`.
- No "run it yourself" for the LLM harnesses. Datasets are private (Q3).

Each table must state its operating point explicitly (`t=0.0` for screening, `cv_ats_match_score >= 80` for fit assessment, `K=150` for retrieval) because all three harnesses also publish sweeps, and a number lifted out of a sweep without its threshold is meaningless.

Dashboard spotlight GIF sits in this section, under a subheading that ties it to the offline numbers — the benchmarks prove the gates work on a fixed dataset, the dashboard proves the same spend is tracked per agent and per model in production.

### `docs/evals.md`

The loop, using the real entry points, written for the **maintainer** (the only person who has the datasets): `scripts/export_screening_benchmark_dataset.py` → `uv run run-screening-benchmark` → report under `benchmarks/screening/reports/` → prompt or model change → re-run. Same shape for the other two, noting that retrieval regenerates from an existing screening dataset.

State the artifact policy in one place: datasets are private; reports (markdown + `.results.jsonl` + ranked-uid list) are public; `baseline.json` files stay committed as regression floors. That is also why a stranger cannot reproduce a screening, fit-assessment, or retrieval *run*. They can recompute retrieval metrics and the Q1 composition from the public ranked-uid list plus screening `.results.jsonl`.

Two-tier structure: a **benchmark** you run deliberately when changing a prompt or a model, and a **frozen regression floor**. Retrieval's second tier becomes `baseline.json` + a CI assertion over the committed ranked-uid list (Q9). The OpenSearch re-index path in `test_retrieval_smoke.py` remains a maintainer test, skipped when the private corpus is absent. Screening has a committed `baseline.json` pinning `glm-5.3-flash` against `20260915_130230` — that pin is the bake-off destination, not a claim that glm is already live (Q4). Fit assessment has neither.

*What the benchmarks decided*, to confirm in prose rather than assert:

- Live env still runs `gpt-5.6-luna` for screening, fit assessment and cover letters. The screening-gate bake-off selected `glm-5.3-flash` (luna-on-reordered packaging missed Fitting Recall 0.800); that switch is decided and not yet deployed. Fit-assessment/cover-letter defaults in `config.py` still say `gpt-5-mini` with no pending switch — those get aligned to luna.
- Production screening ignores the confidence score. The sweep supports this directly: confidence clusters at mean 0.946 and cutoffs below 0.9 move nothing (`20260909_115647` sweep rows for t=0.5–0.8).
- The pair gate moved from a fixed top-K to a ratio of the batch (`cb364f2`); the retrieval report is re-headlined to K=150 to match.

Honest caveats (dataset is one candidate, gold labels are historical production assessments rather than independent human labels) live here, not in the README.

### Dashboard spotlight

Recorded from Grafana Cloud against real pipeline data (Q6). Lives under `docs/assets/` (Q7), inside Evaluation. A ~15–20 second loop over the LLM Cost & Token Accounting dashboard, starting on the four stat panels, scrolling to the burn-rate timeseries and the prompt/completion donut, ending on the per-agent/model efficiency table, with one `$agent` variable change mid-way. Crop or pan off the Cloud org name if it appears in the chrome.

### Correctness fixes

In scope because publishing the numbers without them is the risk, not the documentation gap:

- `.env.example` with every variable from `README.md:276-289` plus the optional tuning list at `README.md:291`, values blanked — lives next to the operator setup in `docs/architecture.md`, not as a quick-start promise.
- `FIT_ASSESSMENT_MODEL` and `COVER_LETTER_MODEL` defaults in `config.py` aligned to `gpt-5.6-luna`. Leave `SCREENING_MODEL` at `glm-5.3-flash`. Docs that list defaults state the screening exception: config default is glm, live env still luna until the switch (Q4).
- `benchmarks/screening/README.md` and `benchmarks/fit_assessment/README.md` — datasets private, reports public; fix the screening README claim that `reports/` is gitignored (it is not). Broken link `docs/planning/screening-agent.md` → `docs/planning/archive/`.
- `.gitignore`: ignore `benchmarks/retrieval/dataset/*` except `baseline.json` (and `.gitkeep` if needed); stop ignoring `benchmarks/retrieval/reports/`. `git rm --cached` the retrieval corpora and `candidate.json`. History is left alone.
- `scripts/run_retrieval_benchmark.py` headline `@20` → production K (Q2); emit ranked uids for Phase 1b (Q1, Q9).
- CI: `.github/workflows/ci.yml` OpenSearch job keeps `tests/integration/test_search_service.py` and drops the corpus-backed retrieval smoke. The ranked-uid assertion runs in the unit-test job (Q9).

## Open questions

None. All questions are in the Decision log.

## Decision log

### Q1 — Headline number is the measured retrieval+screening composition

**Decided:** 2026-09-15
The above-the-fold cost/accuracy claim is the **measured** composition of hybrid retrieval at the production ratio (K=150 on this corpus) with screening predictions replayed over that top-K set. The retrieval harness emits a ranked-uid list; a composition step intersects it with the committed screening `.results.jsonl` (luna, matching what the live env runs today — Q4). Zero new LLM calls. The resulting reduction, cost and good/fitting recall are committed as a report and linked from the README. Do not publish the historical 23% single-gate or 61% estimated-composition figures.

**Rejected:** (a) screening-gate-only — does not describe the architecture being sold, and the honest single-gate number has already gone negative in production telemetry. (b) labelled estimate — a reviewer must trust an assumption (screening drop rate holds on the retrieved subset) that production already measured as false (51.7% vs 64%).

**Consequence:** Phase 1b exists. After Q3 the ranked-uid list and screening results are the public, checkable inputs; the corpus can stay private. Which luna `.results.jsonl` to replay (pre- vs post-packaging) is an implementation choice: use the run that matches the prompt packaging currently in the live env. When screening switches to glm, the composition is a replay against `20260915_130230_glm-5.3-flash.results.jsonl` — no new LLM calls then either. Q9 uses the same ranked-uid list as the CI floor.

Unblocks Q1 from [`screening-gate-cost-reduction-implementation-plan.md`](screening-gate-cost-reduction-implementation-plan.md), which is now Implemented. That plan's packaging/bake-off reports are inputs to the composition, not a reason to keep Q1 open.

### Q2 — Retrieval reports headline the production operating point (K=150)

**Decided:** 2026-09-15
Re-headline `scripts/run_retrieval_benchmark.py` (currently hardcoded `@20`) to the production operating point implied by `PIPELINE_RETRIEVAL_RATIO=0.5` → K=150 on this 300-job corpus. Commit the regenerated report. Combined with Q3, `benchmarks/retrieval/reports/` is tracked.

**Rejected:** (b) leave the harness alone and footnote K=150 in the README — the report would keep misdescribing production to anyone who opens it. (c) omit retrieval from the README — hides the larger gate.

**Consequence:** no LLM re-run; the K=150 rows are already in the sweep. The JSON the report is rendered from is currently gitignored, so regeneration is local. `baseline.json` already pins `*_at_150`.

**Flagged, not in scope:** a tight top-K gate is not viable on this evidence (hybrid at K=20 retains barely twice random). Product question for a separate plan.

### Q3 — All eval datasets are private; all results are public

**Decided:** 2026-09-15
No eval dataset is committed: screening and fit-assessment stay gitignored (screening's `baseline.json` exception remains), and retrieval corpora / `candidate.json` / `extracted_profile.json` are untracked to match. All harness **results** are committed: screening and fit-assessment reports already are; stop ignoring `benchmarks/retrieval/reports/`. `docs/evals.md` states this policy plainly. There is no "run it yourself" for a stranger.

**Rejected:** (a) commit `entries.jsonl` without `cv.pdf` — still leaks job text and gold labels, and the retrieval `candidate.json` PII problem is left inconsistent. (b) synthetic CV — effort spent to weaken the labels. (c) commit everything including the CV — the opposite privacy call.

**Consequence:** the credential-free retrieval eval (committed embeddings, no API key) ceases to be a public artifact; that path was also the abandoned Q8 quick start. Untracking the corpus without Q9 would break CI; Q9 closed that. `git rm --cached` does not remove the files from history; history rewrite is out of scope. Benchmark READMEs that claim datasets are tracked, or that screening `reports/` is gitignored, get corrected in Phase 1.

### Q4 — Publish the luna reports that match what's running; do not revert the glm screening default

**Decided:** 2026-09-15 (amended same day: glm switch is pending, not rejected)
Do not re-run fit assessment on `gpt-5-mini`. The live env still sets `SCREENING_MODEL`, `FIT_ASSESSMENT_MODEL` and `COVER_LETTER_MODEL` to `gpt-5.6-luna`, so the committed luna reports are what the running instance actually pays. The screening-gate bake-off still stands: `glm-5.3-flash` is the decided next screening model; it has not been switched in production yet. Leave `SCREENING_MODEL` default at `glm-5.3-flash`. Align only `FIT_ASSESSMENT_MODEL` and `COVER_LETTER_MODEL` from `gpt-5-mini` to `gpt-5.6-luna` — there is no pending switch for those two.

README tables state the model that is running today (luna). `docs/evals.md` tells the bake-off story and that the glm screening switch is decided but not deployed. Screening `baseline.json` keeps the glm pin.

**Rejected:** (a) re-run on `gpt-5-mini` — that is a stale fit-assessment default, not what production runs. (b) transpose luna token counts onto mini rates — publishes a cost the pipeline does not pay. (c) publish both as the README fit-assessment row — bake-off comparison belongs in `docs/evals.md`. Also rejected, on amendment: reverting `SCREENING_MODEL` to luna — that would undo the bake-off default before the env has even caught up.

**Consequence:** Q1's composition uses luna screening results and luna assessment cost, matching the live env. After the glm switch, replay the same ranked uids against the committed glm `.results.jsonl`. Docs that list "default models" must distinguish screening's glm default from the luna env override until the switch lands.

### Q5 — Hero is the live UI; a pipeline terminal GIF is optional

**Decided:** 2026-09-15
Above-the-fold asset is a recording of the UI job feed → cover-letter modal, captured from the running production instance (weeks up; deploys from `main`). Link the client repo in the same block. A terminal recording of `uv run run-pipeline` is a worthwhile *second* asset if the recording session is happening anyway; it is not the hero and does not block Phase 3.

**Rejected:** (c) static composite — cheapest and lowest impact. (d) LLM cost dashboard as hero — that GIF belongs in Evaluation, where it supports the eval story rather than pretending to be the product.

**Consequence:** Phase 3 records from the live instance, not from a local `react-app/` checkout. Combined with Q10, pass 1 is the GIF; pass 2 is not a logged-in walkthrough.

### Q6 — Dashboard GIF is recorded from Grafana Cloud; local stack is not restored

**Decided:** 2026-09-15
Record the LLM Cost & Token Accounting GIF from Grafana Cloud against real pipeline data. No change to `monitoring/` or `docker-compose.yml` in this plan. Crop or pan off the Cloud org name if it appears.

**Rejected:** (b) restore provisioning and convert dashboards to a locally-provisionable schema — a real fix, and the original leaning, but out of scope here; it is a monitoring-stack task, not a README-asset task. (c) local stack plus synthetic Prometheus seed — extra generator this plan does not need. (d) public Grafana dashboard link instead of a GIF — interactive until the Cloud instance lapses, and a different artifact story from Q7's in-repo assets.

**Consequence:** Phase 3 is recording-only. `docs/architecture.md` must not claim `docker compose up -d` brings up Grafana. The broken local mounts remain a known defect, to be fixed in a later plan if at all.

### Q7 — Binary assets live in `docs/assets/`

**Decided:** 2026-09-15
Commit stills and GIFs under `docs/assets/`. Self-contained, works on any mirror, including offline.

**Rejected:** (b) GitHub-release / issue CDN URLs — README breaks if the object is removed. (c) stills in-repo, video hosted out of band — splits the artifact story for little gain given Q5/Q8 already dropped the "clone and run" path.

**Consequence:** repo weight grows permanently with every re-record. Phase 3 should still crop and frame-cap so the hero loads before the fold (a 5 MB budget is a recording constraint, not a storage policy).

### Q8 — README splits; no quick start; lead with the live demo

**Decided:** 2026-09-15
Move `Service components`, `MongoDB collections`, env vars and the observability table into `docs/architecture.md`, leaving a README on the order of 120 lines. Do **not** ship a reviewer-facing quick start — too many external dependencies, not feasible that anyone will run it. The landing page's product proof is the hero GIF (Q10); a live URL is optional and secondary. Operator setup (including `.env.example`) remains in `docs/architecture.md` for the person who already operates the instance.

**Rejected:** split (a) prepend and keep everything — one file, gets long, landing and reference keep competing. Split (c) architecture + operations — extra file without a second audience. Quick start (i) honest-but-still-a-quick-start — promises a path nobody will complete. Quick start (ii) lead with credential-free retrieval — killed twice, by this decision and by Q3 making the retrieval corpus private.

**Consequence:** roadmap action 2 (zero-credential demo mode) stays out of scope; this plan does not leave a placeholder "coming soon" block for it. Roadmap action 4 is not *built* here. `docs/architecture.md` is also a landing pad for a later case study (roadmap 6) without pretending this plan writes that essay.

### Q9 — Retrieval CI asserts the committed ranked-uid list, not a live OpenSearch re-run

**Decided:** 2026-09-15
Drop the corpus-backed OpenSearch re-run from CI. Assert the committed ranked-uid artifact (the same list Q1 emits) against `baseline.json`, the same shape screening intends: public results, private dataset. The existing `test_retrieval_smoke.py` OpenSearch path stays as a maintainer test, skipped when the corpus is absent. The CI OpenSearch job keeps `tests/integration/test_search_service.py` only. The ranked-uid assertion runs in the unit-test job (no OpenSearch).

**Rejected:** (a) skip when corpus is absent — GitHub CI would never run the floor. (b) redacted CI fixture — a second dataset to keep in sync, and a privacy leak in miniature. (d) keep the corpus tracked — contradicts Q3.

**Consequence:** Phase 1 must stop invoking the corpus-backed smoke in CI in the same change that untracks the corpus, or CI goes red. Phase 1b emits the ranked-uid list and wires the assertion. Until 1b lands, CI has no retrieval quality floor; that gap is accepted and short. Pin `baseline.json` to the dataset version the ranked-uid list was generated from.

### Q10 — Hero GIF is the no-login preview; live URL is secondary with no sign-in promise

**Decided:** 2026-09-15
The GIF is what a reviewer without credentials sees. A link to the running instance may appear, framed as the author's deployment, with no promise a stranger can sign in and no demo-account flow built in this plan.

**Rejected:** (a) lead with a public URL behind Auth0 as today — a login wall is not a demo. (b) URL plus documented demo login — better if a demo account already existed; it does not, and building one is roadmap 4, out of scope.

**Consequence:** Phase 4 copy does not say "try it" or "sign in". Pass 1 is the GIF plus headline numbers. Pass 2 is whatever a motivated reviewer does with the URL on their own.

## Implementation phases

All questions are closed. Phases are ordered and independently reviewable. Phase 3 can proceed in parallel with 1–2.

### Phase 1 — Harness and repo truthfulness

**Depends on:** nothing remaining
**Reviewable when:** retrieval reports headline K=150 and are committed; datasets are untracked except `baseline.json`; `FIT_ASSESSMENT_MODEL` and `COVER_LETTER_MODEL` defaults are luna while `SCREENING_MODEL` stays glm; benchmark READMEs describe the private-dataset / public-results policy; the CI OpenSearch job no longer runs the corpus-backed retrieval smoke; `.env.example` exists for operator docs.
**Touches:** `scripts/run_retrieval_benchmark.py` (headline only; ranked-uid emit is 1b), `.gitignore`, `benchmarks/*/README.md`, `benchmarks/retrieval/reports/`, `benchmarks/retrieval/dataset/` (untrack), `config.py` (fit-assessment and cover-letter defaults only), `docs/langgraph-orchestration.md`, `.env.example`, `.github/workflows/ci.yml`, `benchmarks/retrieval/test_retrieval_smoke.py` (skip without corpus)

Untrack and the CI change land together.

### Phase 1b — Composed gate measurement and CI floor

**Depends on:** Phase 1
**Reviewable when:** a committed report states the compounded reduction rate and good/fitting recall of retrieval + screening over corpus `05082026`, reproducible from the committed ranked-uid list and the stored screening predictions without any LLM call; CI unit tests assert that ranked-uid list against `baseline.json`.
**Touches:** `scripts/run_retrieval_benchmark.py` (emit ranked uids), a new composition step, `benchmarks/retrieval/reports/`, `benchmarks/retrieval/test_retrieval_smoke.py` (artifact assertion), `.github/workflows/ci.yml` (run that assertion in the unit-test job)

### Phase 2 — Evaluation content

**Depends on:** Phase 1, Phase 1b
**Reviewable when:** `docs/evals.md` and the README Evaluation section exist, every number links to the report it came from, every table states its operating point, and the artifact policy (private datasets, public results) is stated once.
**Touches:** `docs/evals.md`, `README.md`

### Phase 3 — Assets

**Depends on:** nothing remaining (Q5, Q6, Q7). Independent of Phases 1–2 except for where the GIF is captioned.
**Reviewable when:** the UI hero (and optional pipeline terminal GIF) and the Grafana Cloud dashboard GIF exist under `docs/assets/` at a fold-friendly size. Org name is not visible in the dashboard recording.
**Touches:** `docs/assets/` only

### Phase 4 — README landing page

**Depends on:** Phases 2 and 3
**Reviewable when:** the first screen carries pitch, badges, hero GIF and headline numbers; any live URL is secondary with no sign-in promise; nothing above the fold is unverifiable; reference material lives in `docs/architecture.md` and does not claim a working local Grafana.
**Touches:** `README.md`, `docs/architecture.md`
