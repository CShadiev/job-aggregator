# DeduplicationAgent: Testing Strategy

## Scope

This document describes how to test `DeduplicationAgent` — the AI-backed component that
normalises job titles and company names so downstream deduplication can match variants
like "Google Inc." / "Google" or "Sr. Software Engineer" / "Senior Software Engineer".

**In scope**

- `DeduplicationAgent.normalize()` — batching, concurrency, result aggregation
- `DeduplicationAgent._process_batch()` — prompt assembly, agent invocation, error handling
- `DeduplicationAgent._reconcile()` — mapping AI output back to original `JobPosting` objects
- Pydantic models in `models/deduplication.py` used as the agent output contract

**Out of scope (separate test plans)**

- `CollectionService.deduplicate()` — deterministic UID / key / recency logic that *consumes*
  normalised fields but does not call the agent
- End-to-end collection pipeline tests (`get_normalized_jobs`) — covered under collection-service
  testing (see `TODO.md`)

---

## Component under test

```
normalize(postings)
    │
    ├─ split into batches (DEDUPLICATION_BATCH_SIZE)
    ├─ asyncio.gather → _process_batch(batch)  [concurrent]
    │       │
    │       ├─ build temp_map { "0": posting, … }
    │       ├─ format prompt from normalize_job.md
    │       ├─ agent.run(prompt) → NormalizedBatch
    │       └─ _reconcile(temp_map, output)
    │
    └─ merge processed + failed → NormalizationResult
```

The agent depends on:

| Dependency | Role |
|---|---|
| `pydantic_ai.Agent` | Structured LLM call; output type `NormalizedBatch` |
| `agents/prompt_templates/normalize_job.md` | Normalisation rules and `{jobs_to_process}` placeholder |
| `ConfigProvider.get_config().DEDUPLICATION_BATCH_SIZE` | Batch size (default `50`) |

**Note:** `DEDUPLICATION_MAX_RETRIES` exists in config but is not yet wired into
`DeduplicationAgent`. When retries are implemented, add tests for partial-batch retry
behaviour and exhausted-retry failure paths.

---

## Test pyramid

| Layer | Purpose | LLM calls | Marker |
|---|---|---|---|
| Unit | Pure logic, fast feedback | None | — |
| Component | Agent orchestration with stub model | None (mocked) | — |
| Evaluation | Normalisation quality on a gold set | Yes (paid) | `@pytest.mark.priced` |

Default CI runs unit + component tests only. Evaluation tests require `--run-priced`
(see `tests/conftest.py`).

---

## Layer 1 — Unit tests

Target file: `tests/unit/test_deduplication_agent.py`

These tests need no network, no API keys, and no LLM. They should run in milliseconds.

### `_reconcile()` (highest priority)

`_reconcile` is deterministic and carries the most business risk: a bug here silently drops
postings or attaches normalised fields to the wrong record.

| Case | Input | Expected |
|---|---|---|
| Happy path | `temp_map` with N entries; `NormalizedBatch` with matching N ids | N processed postings; `title_normalized` / `company_normalized` set via `model_copy`; empty `failed` |
| Partial response | AI returns fewer entries than input | Missing ids appear in `failed` with error `"AI did not return a result for this posting."` |
| Unknown id | AI returns an id not in `temp_map` | Entry ignored; no crash |
| Duplicate id in AI output | Same id twice in `normalized.jobs` | First wins; second ignored (id already in `seen_ids`) |
| Empty batch output | `NormalizedBatch(jobs=[])` | All postings in `failed` |
| Field mapping | Known `title` / `company` in AI entry | Original posting fields unchanged except normalised columns |

Use a small `JobPosting` factory (see [Fixtures](#fixtures)) so tests stay readable.

### `normalize()` batching

Test batch splitting without calling the real agent by patching `_process_batch`:

| Case | Setup | Assert |
|---|---|---|
| Empty input | `normalize([])` | `NormalizationResult(processed=[], failed=[])` |
| Single batch | `len(postings) ≤ batch_size`; stub returns known result | One `_process_batch` call |
| Multiple batches | `len(postings) > batch_size`; stub returns per-batch results | Correct number of calls; merged `processed` / `failed` preserve order within each batch |
| Concurrent batches | Multiple batches; stub sleeps briefly | Total wall time ≈ one sleep (validates `asyncio.gather`, not serial execution) |

Override `DEDUPLICATION_BATCH_SIZE` via `monkeypatch.setenv` + reset `ConfigProvider.__config`
(or inject a test config if a helper is added later).

### `_process_batch()` error handling

Patch `agent.run` to raise an exception:

| Case | Assert |
|---|---|
| Agent raises | Entire batch in `failed`; each entry's `error` is `str(exc)`; `processed` empty |
| Agent succeeds | Delegates to `_reconcile`; no exception propagation |

---

## Layer 2 — Component tests (mocked LLM)

Target file: `tests/integration/test_deduplication_agent.py`

Exercise the real `Agent` wiring and prompt assembly while keeping tests deterministic.

### Recommended approach: `FunctionModel`

PydanticAI provides [`FunctionModel`](https://ai.pydantic.dev/api/models/function/) for
replacing the LLM with a local function. Use `agent.override(model=FunctionModel(...))` on
the inner `DeduplicationAgent.agent` instance.

Set globally in `conftest.py` or per test:

```python
from pydantic_ai.models import ALLOW_MODEL_REQUESTS

ALLOW_MODEL_REQUESTS = False  # fail fast if a real model is accidentally used
```

The `FunctionModel` callback receives `messages` and can:

1. Parse the user prompt and assert `{jobs_to_process}` JSON contains expected ids, titles, companies
2. Return a `ModelResponse` that satisfies the structured output tool for `NormalizedBatch`

Alternatively, for simpler cases, patch `DeduplicationAgent.agent.run` with `AsyncMock` returning
an object whose `.output` is a `NormalizedBatch`. This is sufficient when prompt content is
not under test.

### Cases to cover

| Case | What to verify |
|---|---|
| End-to-end normalize | Mock returns normalised entries for all ids → all in `processed`, fields populated |
| Prompt payload | Serialized jobs use batch-local string ids `"0"`, `"1"`, … and include `title` / `company` only |
| Template load | Agent initialises without error; prompt contains normalisation rules from `normalize_job.md` |
| Multi-batch merge | Two batches with distinct mock responses → combined result length matches input |

---

## Layer 3 — Evaluation tests (optional, priced)

Target file: `tests/evaluation/test_deduplication_agent.py`

These tests call a real model and validate *normalisation quality*, not wiring. Mark with
`@pytest.mark.priced` so they are skipped unless `--run-priced` is passed.

### Gold set

Maintain a JSON or YAML fixture, e.g. `tests/fixtures/deduplication_gold.json`:

```json
[
  {
    "title": "Sr. Software Engineer (m/w/d)",
    "company": "Google Inc.",
    "expected_title": "senior software engineer",
    "expected_company": "google"
  }
]
```

Each row is turned into a `JobPosting`, run through `normalize()`, and compared against
expected normalised fields.

### Quality assertions

| Assertion type | Rationale |
|---|---|
| Exact match on gold set | Catches regressions when the prompt or model changes |
| Equivalence classes | Pairs like `("Google", "Google Inc.")` should produce identical `company_normalized` |
| Consistency | Same input run twice → same output (within model stochasticity tolerance) |
| Completeness | No unexpected entries in `failed` for well-formed gold inputs |

Use soft thresholds for evaluation: log mismatches and fail only when accuracy on the gold
set drops below an agreed baseline (e.g. 95% exact match on company, 90% on title).

### Edge cases from the prompt contract

Draw cases directly from `normalize_job.md` rules:

- Legal suffixes: GmbH, AG, LLC, Inc.
- Title abbreviations: Sr., Jr., Eng., Dev., Mgr.
- Special characters and accents in company names
- Gender / location noise in titles: `(m/w/d)`, `remote`, `hybrid`
- Technology suffixes: `Developer Python`, `Senior Web Developer Python FastAPI`

---

## Fixtures

Add shared helpers under `tests/` to avoid duplicating boilerplate.

### `make_job_posting(**overrides) -> JobPosting`

Minimal valid `JobPosting` with sensible defaults (`uid`, `source`, timestamps, etc.).
Tests override only `title` and `company` unless they need other fields.

### `make_normalized_batch(entries: list[tuple[str, str, str]]) -> NormalizedBatch`

Build `NormalizedBatch` from `(id, title, company)` tuples for `_reconcile` and mock tests.

### Config isolation

`ConfigProvider` caches config on first access. In tests that change env vars:

1. `monkeypatch.setenv("DEDUPLICATION_BATCH_SIZE", "2")`
2. Reset `ConfigProvider._ConfigProvider__config = None` before constructing the agent

Consider a `pytest` fixture that resets config automatically after each test.

---

## Suggested file layout

```
tests/
├── conftest.py                          # priced marker (existing)
├── fixtures/
│   └── deduplication_gold.json          # evaluation gold set
├── helpers/
│   └── job_posting.py                   # make_job_posting, make_normalized_batch
├── unit/
│   └── test_deduplication_agent.py      # _reconcile, batching, error paths
├── integration/
│   └── test_deduplication_agent.py      # FunctionModel / mocked agent.run
└── evaluation/
    └── test_deduplication_agent.py      # @pytest.mark.priced
```

---

## Running tests

```bash
# Default — unit + component (no LLM cost)
uv run pytest tests/unit/test_deduplication_agent.py tests/integration/test_deduplication_agent.py

# Include evaluation / live model tests
uv run pytest --run-priced tests/evaluation/test_deduplication_agent.py
```

---

## Implementation order

1. **`_reconcile` unit tests** — pure logic, highest defect density, no mocks
2. **`_process_batch` error path** — ensures failed batches surface in `NormalizationResult.failed`
3. **`normalize` batching** — validates config-driven split and merge
4. **Component test with mocked `agent.run`** — smoke test for the public API
5. **Gold-set evaluation** — once a stable prompt and model are chosen; run locally or in a scheduled job, not on every PR

---

## Open questions

- **Which model for evaluation?** Record the model id in the gold-set test module so regressions are comparable across runs.
- **Retry semantics:** When `DEDUPLICATION_MAX_RETRIES` is implemented, should retries be per-batch or per-posting? Tests should match the chosen design.
- **Normalisation dictionary:** `TODO.md` mentions a future agent-maintained dictionary of known titles and companies. When added, unit tests should cover lookup-before-LLM and merge-with-AI-output behaviour.
