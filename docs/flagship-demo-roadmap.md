# Turning Job Aggregator into a Flagship Demo Application

*A career-advisor recommendation. Actions are sorted by approximate value-to-time ratio, assuming AI-assisted development.*

## The core assessment

The engineering substance of this project is already flagship-grade — arguably stronger than most portfolio projects by senior candidates:

- A checkpointed LangGraph pipeline with idempotent fan-out over user × job pairs.
- Four PydanticAI agents (normalization, screening, fit assessment, cover letter) with a **cost-gating architecture** (cheap screening before expensive assessment).
- **Offline benchmark harnesses with committed datasets and reports** for screening, fit assessment, and retrieval — genuine eval-driven AI development, which is rare and highly valued right now.
- Hybrid OpenSearch retrieval with embeddings, a full Prometheus/Grafana/Alloy/OTel observability stack, per-model LLM pricing tracking, Auth0, CI, Docker publishing, ruff + pyright.

The problem is not depth — it's **discoverability and demonstrability**. A reviewer evaluates a portfolio project in three passes:

1. **30 seconds** — README above the fold, screenshots, a live link. *Currently: a good but text-only README; the strongest assets (benchmarks, dashboards) are buried or invisible.*
2. **5 minutes** — can they run it or click around a live instance? *Currently: no — it requires Apify, OpenAI, DeepInfra, Grok, Auth0, and S3 credentials plus real scraped data. Nobody will get past `.env`.*
3. **30+ minutes** — code quality, tests, design docs. *Currently: this pass is excellent, but almost no reviewer reaches it.*

Every high-ratio action below moves value from pass 3 into passes 1 and 2.

---

## Priority table

| # | Action | Value | Time (AI-assisted) | Ratio |
|---|--------|-------|--------------------|-------|
| 1 | README as a landing page (screenshots, GIF, results up front) | Very high | 2–4 h | ★★★★★ |
| 2 | Zero-credential demo mode: one command, seeded data, no external keys | Very high | 1–2 days | ★★★★★ |
| 3 | Surface the benchmarks as a headline "Evals" section + case study | High | 3–5 h | ★★★★★ |
| 4 | Hosted live demo with a read-only demo account | Very high | 1–2 days | ★★★★ |
| 5 | Frontend: pipeline/assessment visibility (dashboard + fit detail view) | High | 2–3 days | ★★★★ |
| 6 | Architecture case-study write-up (decisions and tradeoffs) | High | 3–5 h, mostly yours | ★★★★ |
| 7 | Expose cost & observability as a feature (Grafana screenshots, per-run LLM cost) | Medium-high | 0.5–1 day | ★★★ |
| 8 | Finish the CV-tailoring feature (open TODO) | Medium-high | 2–4 days | ★★★ |
| 9 | Self-serve onboarding (CV upload, profile wizard) | Medium | 3–5 days | ★★ |
| 10 | Wire StepStone/Indeed collectors | Low-medium | 1–2 days | ★★ |
| 11 | Broader E2E tests, coverage badge | Low-medium | 1–2 days | ★★ |
| 12 | Kubernetes/Terraform/IaC | Low (unless targeting platform roles) | 3–5 days | ★ |

---

## Tier 1 — do these first (highest ratio)

### 1. README as a landing page — 2–4 hours

The single cheapest, highest-impact change. The current README explains the system well but *shows* nothing. Add, in order, above the current content:

- One hero screenshot or 20–30 s GIF of the job feed with fit scores and a generated cover letter.
- A three-line pitch framing it as a product: *"Scrapes jobs from N sources, deduplicates them with AI-normalized keys, scores each against your CV with a cost-gated two-stage agent pipeline, and drafts cover letters for the best matches."*
- Headline numbers: jobs processed, benchmark accuracy figures (you already have the reports in `scripts/*_benchmark_report.md`), cost per pipeline run.
- Badges: CI, GHCR image, Python/React versions.
- A "Try it in 2 minutes" block (depends on action 2).

AI can generate the structure and copy; you supply the screenshots. Nothing else on this list pays off until this exists.

### 2. Zero-credential demo mode — 1–2 days

Today the project is un-runnable without six external services. Add a `demo` profile that a stranger can start with one command:

- `docker compose --profile demo up`: seeds MongoDB and OpenSearch with a curated snapshot of real (anonymized) jobs, a sample user profile and CV, pre-computed assessments and cover letters.
- A `DEMO_MODE` config flag that bypasses Auth0 with a fixed demo user and stubs LLM calls with recorded responses (you already have recorded datasets in `benchmarks/` to draw from), so the pipeline itself can be run end-to-end for free.
- Local MinIO container standing in for S3.

This converts "trust me, it works" into "run it yourself." It's the difference between a repo and a demo. AI-assisted, most of this is fixture plumbing and a seed script — well-bounded work.

### 3. Make the benchmarks a headline — 3–5 hours

The eval harnesses are your strongest differentiator for AI-engineering roles, and right now they're invisible (buried in `scripts/` and `benchmarks/`). Do three things:

- Add an "Evaluation" section to the README with the actual metrics tables from the screening, fit-assessment, and retrieval reports, plus one sentence each on methodology.
- Add a short `docs/evals.md` explaining the loop: dataset export → benchmark run → model/prompt change → re-run. Mention concrete decisions the benchmarks drove (e.g., model selection for screening vs. assessment).
- Show a cost/accuracy tradeoff: "screening gate drops X % of pairs before assessment, cutting cost per run by Y % at Z % recall." That single sentence is interview gold.

---

## Tier 2 — high value, more effort

### 4. Hosted live demo — 1–2 days

`ALLOWED_ORIGINS` suggests infrastructure at cshadiev.dev already exists. Put the React app plus API behind a public URL with a "Sign in as demo user" button (read-only, seeded data — reuses action 2's work). A clickable link in the README/CV outperforms any amount of prose. Keep costs bounded: demo mode with stubbed LLMs means no per-visitor spend.

### 5. Frontend visibility of the interesting machinery — 2–3 days

The UI currently shows a job list, filters, and a cover-letter modal — it under-sells the backend. The pipeline, agents, and scoring are the impressive parts, so put them on screen:

- **Fit assessment detail view**: per-job breakdown of ATS scores, deal breakers, and the agent's summary — this is the "wow" screen.
- **Pipeline dashboard page**: last run time, jobs collected/deduped per source, pairs screened vs. assessed, cover letters generated. The data all exists in MongoDB already.
- Small polish: loading/empty states, a distinct visual identity beyond default AntD.

With AI assistance, React/AntD pages over existing endpoints are fast; budget most of the time for the one or two new read-only API endpoints.

### 6. Architecture case study — 3–5 hours

Write (or turn into a blog post) a decisions-and-tradeoffs narrative: why LangGraph with a Mongo checkpointer instead of Celery/cron; why a two-stage screen-then-assess gate; why hybrid retrieval; how idempotent pair nodes make the pipeline restartable. You have raw material in `docs/` already — this is consolidation, not new research. In interviews, this document *is* the conversation. AI can draft structure, but the judgment calls must read as yours — write those parts yourself.

---

## Tier 3 — worthwhile once the above is done

### 7. Cost & observability as a feature — 0.5–1 day

You track per-model pricing and run a full Grafana stack — most candidates don't. Add dashboard screenshots to the README, and surface "this pipeline run cost $0.42" in the UI or run summary. LLM cost engineering is a hot topic; make yours visible.

### 8. CV tailoring (open TODO) — 2–4 days

A genuinely useful new agent feature and a good live-demo moment ("here's my CV re-weighted for this posting, with a diff view"). Ship it behind the same eval discipline — a small benchmark dataset — and it reinforces the story from action 3.

### 9. Self-serve onboarding — 3–5 days

CV upload + profile wizard turns the demo from "watch my account" into "try it on *your* CV." High wow-factor but real scope (validation, PDF parsing edge cases, per-user pipeline triggering, abuse/cost controls on a public instance). Do it only after the hosted demo exists.

### 10–11. More sources, more tests — 1–2 days each

Wiring StepStone/Indeed (parsers already exist) and widening E2E coverage are solid but low-visibility. A reviewer can't tell the difference between four sources and six; do these when the demo surface is done.

---

## What *not* to spend time on

- **Kubernetes/Terraform** — days of work a reviewer will never see, unless you're specifically targeting platform/DevOps roles.
- **Refactors and rewrites** — the code quality is already a pass-3 strength; polishing it further has near-zero marginal value compared to fixing passes 1 and 2.
- **More LLM providers/models** — the model factory abstraction already makes the point.

## Suggested sequence

**Week 1:** actions 1 + 3 (one focused day), then action 2. At the end of the week a stranger can run the full system in two minutes and the README sells it.
**Week 2:** actions 4 + 5 — live demo plus the assessment/pipeline UI.
**Week 3:** actions 6 + 7, then pick 8 or 9 depending on whether you're positioning for AI-engineering roles (8) or product-engineering roles (9).

## Positioning note

Present this as an **AI product-engineering** project, not a scraper: the headline is the cost-gated multi-agent pipeline, benchmark-driven quality, and production observability. That combination — agents *plus* evals *plus* ops — is exactly what teams shipping LLM features struggle to hire for in 2026.
