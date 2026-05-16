# German IT Job Aggregation Service

Aggregates job postings from multiple sources, normalizes them into a common schema, and supports candidate-job matching and ranking.

## What this service does

- Collects jobs from multiple providers.
- Normalizes and deduplicates records using AI-assisted key normalization.
- Supports AI-powered matching and enrichment workflows.
- Exposes job data and candidate state through an API.
- Powers a frontend for job discovery and application tracking.

## Supported sources

| Source | Integration |
|---|---|
| StepStone | via Apify |
| Indeed | via Apify |
| Arbeitnow | Direct API |

## Tech stack highlights

| Concern | Technology |
|---|---|
| Pipeline orchestration | Celery + Redis |
| AI agents | PydanticAI + Anthropic |
| API | FastAPI |
| Frontend | React |

---

## High-level architecture

```mermaid
flowchart TD
    SS[StepStone via Apify] --> COL[Collection Service]
    IN[Indeed via Apify] --> COL
    AN[Arbeitnow API] --> COL

    COL --> Q[Celery Task Queue]

    Q --> KN["AI: Key Normalization (batch)"]
    KN --> DD[Cross-source Deduplication]
    DD --> ENR["AI: Description Enrichment (batch, optional)"]

    ENR --> DB[(Job Descriptions)]
    ENR --> FILT[Hard Requirement Filter]

    FILT --> AIFIT["AI: Fit Assessment (batch)"]
    AIFIT --> AS[(Assessments & Rankings)]

    DB --> API[FastAPI Server]
    AS --> API

    API --> FE[React Frontend]
    API --> NS[Notification Service - optional]
```

---

## Service components

### Collection service

Ingests job postings from all supported sources and maps them to a shared schema. Manages source-specific collectors and hands completed batches off to the processing pipeline.

#### Collectors

Source-specific adapters that handle the details of each provider's API.

- `ApifyCollector` — integrates with the Apify platform to run and retrieve actor results.
- `ArbeitnowCollector` — calls the Arbeitnow REST API directly.

### Processing pipeline

A Celery task chain that transforms and validates each batch of collected jobs before writing them to the database. All AI steps operate on batches to reduce latency and API cost.

| Step | Responsibility |
|---|---|
| Key normalization | Consistent job title and company name across sources |
| Cross-source deduplication | Collapse duplicate postings from different providers |
| Description enrichment *(optional)* | Extract structured properties from free-text descriptions; enriched records are persisted to the job descriptions store and **also** forwarded to the fit assessment pipeline |
| Hard requirement filter | Discard jobs that fail mandatory criteria (language, required technologies, years of experience, etc.) before any AI scoring |
| AI fit assessment | Score each surviving job against all candidate profiles; write results to a separate assessments store |

### AI agent — key normalization

A PydanticAI agent that standardizes job titles and company names across sources. Consistent keys are a prerequisite for reliable cross-source deduplication.

### AI agent — description enrichment *(optional)*

A PydanticAI agent that extracts structured properties from job description text — for example, tech stack, required seniority, and years of experience. Enables personalized candidate feeds without per-candidate fit scoring on every job.

### Fit assessment pipeline

A two-step pipeline that runs in parallel with job persistence after enrichment.

1. **Hard requirement filter** — rule-based pre-filter that drops jobs failing mandatory criteria (posting language, required technologies, minimum years of experience, etc.) before any AI call is made.
2. **AI fit assessment** — a PydanticAI agent that fetches all candidate profiles and scores each job that passed the filter. Results are written to a separate assessments collection so that job records and fit scores remain independently queryable.

### API server (`FastAPI`)

Provides REST endpoints for fetching and filtering ranked job feeds, managing candidate profiles, and tracking application status (applied, shortlisted, rejected, etc.).

### Frontend (`React`)

User interface for profile management, browsing ranked jobs, and tracking application progress.

### Notification service *(optional)*

Sends digest or real-time notifications about new relevant jobs based on candidate preferences.

---

## Job processing flow

```mermaid
flowchart TD
    A([Collection triggered]) --> B{Source type}

    B -->|Apify| C["Run Apify actor — repeat with adjusted params until earliest date reaches checkpoint"]
    B -->|Arbeitnow| D["Paginate Arbeitnow API until earliest date reaches checkpoint"]

    C --> E[Source-level deduplication by unique ID]
    D --> E

    E --> F[Celery: normalize job titles and company names — batch]
    F --> G[Cross-source deduplication by normalized keys + time window]
    G --> H{Enrichment enabled?}
    H -->|Yes| I[Celery: extract structured properties from descriptions — batch]
    H -->|No| J

    I --> J[(Persist jobs to database)]
    I --> L[Hard requirement filter — language, technologies, experience, etc.]
    H -->|No| L

    L --> M[Celery: AI fit assessment — fetch candidate profiles, score each job — batch]
    M --> N[(Assessments persisted to separate table)]
```
