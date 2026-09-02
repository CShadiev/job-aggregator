# Epic 1: Developer Foundation, CI Quality Gates & Baseline Telemetry

**Status:** Planned  
**Scope:** Local containerized stack, codebase cleanup, comprehensive CI pipeline, baseline OpenTelemetry tracing, and frontend integration.  
**Demonstrable Outcome:** A clean, automated developer loop where every pull request is linted, type-checked, and tested in CI, running against a reproducible local multi-service environment (`docker-compose`) with end-to-end trace correlation and frontend connectivity.

---

## 1. Problem Statement & Motivation

Before building advanced search tiers or RAG pipelines, the developer loop needs a rock-solid foundation:
1. **No Automated CI Gates:** CI currently only builds and pushes Docker images on tag triggers; pull requests lack automated linting, static type checking, and integration test runs.
2. **Local Multi-Service Disparity:** Running FastAPI, MongoDB, and upcoming search/telemetry services locally requires ad-hoc scripts rather than a single unified local stack.
3. **Dead Code & Hygiene Debt:** The codebase still contains legacy orchestration files (`workers/job_processing.py`), obsolete database collections, single-stage unoptimized Dockerfiles, and open CORS settings.
4. **Zero Request Tracing:** Requests through the API and executions through LangGraph nodes lack correlation IDs and trace propagation, making downstream debugging and cost accounting difficult.

---

## 2. Vertical Slice Deliverables

### A. Application & Local Developer Environment
- **Local Compose Stack (`docker-compose.yml`):**
  - Stand up MongoDB (with replica set if needed for change streams/transactions).
  - Stand up a single-node OpenSearch 2.19+ container with persistent volume and pre-allocated heap (512MB–1GB for local dev).
  - Stand up LocalStack / MinIO for S3-compatible object storage mock (or direct local storage abstraction).
- **Codebase Hygiene & Dead Code Removal:**
  - Delete legacy `workers/job_processing.py` and remove references to legacy queues (`job_processing`, `failed_entries`).
  - Fix `CORSMiddleware` configuration (restrict origins, allow credentials safely).
  - Optimize `Dockerfile`: multi-stage build, pinned base image digest, non-root user execution, and clean `.dockerignore`.
- **Health & Readiness Endpoints:**
  - Add `/healthz` (liveness) and `/readyz` (dependency check: Mongo ping, search ping).

### B. CI Pipeline & Quality Gates
- **GitHub Actions PR Gate Workflow (`.github/workflows/ci.yml`):**
  - **Lint & Format:** Run `ruff check` and `ruff format --check`.
  - **Type Safety:** Run `mypy` or `pyright` across `api/`, `orchestration/`, `agents/`, `models/`.
  - **Unit Tests:** Fast `pytest` run covering business logic, routing, and Pydantic models.
  - **Integration Tests:** Execute integration tests against GitHub Actions service containers (MongoDB, mock storage).
  - **Docker Build Validation:** Validate multi-stage Docker build succeeds on every PR without pushing.

### C. Observability & Logging Foundation
- **Structured JSON Logging:**
  - Standardize log format using `loguru` / standard logging with JSON formatting.
  - Bind contextual fields: `cycle_id` (pipeline runs), `request_id` (FastAPI requests), `user_id`.
- **OpenTelemetry Instrumentation:**
  - Integrate OpenTelemetry SDK in FastAPI with auto-instrumentation for HTTP requests, PyMongo queries, and external outbound calls.
  - Export spans to standard output in local dev or local OTel Collector.
  - Pass trace context through LangGraph graph state and node executions.

### D. Frontend Integration (Context Hookup)
- **Frontend Workspace Isolation:**
  - Clone/link the existing React UI repo into `react-app/` (ignored in `.gitignore` and `.dockerignore`).
  - Verify frontend API client matches backend schemas (`JobFeedItem`, `JobFeedQuery`, auth headers).
  - Verify local end-to-end communication between the React app and backend API.

---

## 3. Step-by-Step Execution Plan

| Step | Task | Deliverable |
| --- | --- | --- |
| **1.1** | Clean dead code & harden API | Delete `workers/job_processing.py`, clean repo methods, fix CORS. |
| **1.2** | Multi-stage Dockerfile & local compose | `Dockerfile`, `docker-compose.yml` (Mongo + OpenSearch + API). |
| **1.3** | GitHub Actions CI workflow | `.github/workflows/ci.yml` (ruff + mypy + pytest + integration). |
| **1.4** | OpenTelemetry & structured logging | OTel FastAPI/PyMongo middleware, trace/cycle ID propagation. |
| **1.5** | Local UI verification | Clone UI into `react-app/`, test auth and API feed display locally. |

---

## 4. Acceptance Criteria & Verification

- [ ] `docker compose up -d` starts MongoDB, OpenSearch, and API with all services passing health checks.
- [ ] Running `pytest` locally and in GitHub Actions passes 100% of unit and integration tests.
- [ ] Pull requests trigger the automated CI gate (linting, type checking, tests, build) and report status checks.
- [ ] Every incoming API request and LangGraph pipeline cycle produces structured logs containing `request_id` or `cycle_id`.
- [ ] React UI in `react-app/` connects to local API, fetches jobs, and renders without CORS or serialization errors.
