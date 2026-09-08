# Client Search UI — Implementation Plan

**Status:** Ready for implementation
**Last updated:** 2026-09-06
**Open questions:** 0
**Related backend plan:** [hybrid-search-retrieval-eval-implementation-plan.md](./hybrid-search-retrieval-eval-implementation-plan.md)
**Epic:** [epic-02-hybrid-search-retrieval-eval.md](./epic-02-hybrid-search-retrieval-eval.md)

---

## Problem

Candidates browsing the job feed in the frontend web application currently only have access to structured category and floor filters (remote status, location, sources, tags, minimum ATS scores, deal-breakers, and skipped status) inside `react-app/src/pages/jobs/JobFilters.tsx`. 

When candidates want to locate opportunities mentioning a specific technology (e.g. `"Kubernetes"`, `"PyTorch"`, `"Kafka"`), a specific target employer (e.g. `"Google"`, `"Stripe"`), or a role keyword (e.g. `"Staff"`, `"Founding Engineer"`), there is no keyword/text search input available. 

As decided in Backend Epic 2 (decisions Q2, Q10, Q12, Q13):
1. The backend `POST /jobs/search` endpoint accepts an optional `q: str | None = None` parameter. The OpenAPI contract is covered by `tests/integration/test_jobs_api.py`.
2. The search space is strictly restricted to matching (assessed) positions for the authenticated user, powered by an OpenSearch `assessments` index with sub-50ms BM25 multi-match querying across `job.title`, `job.company`, and `job.description`.
3. Client application modifications are planned separately in this artifact and implemented within the frontend repository / environment.

---

## Scope

### In scope

- **Type updates (`react-app/src/types/jobs.ts`):** Extend `JobFeedQuery` and associated form types to support optional text query `q?: string`.
- **Search input UI (`react-app/src/pages/jobs/JobFilters.tsx`):** Add a persistent, prominent keyword search input with search icon, clear button, and placeholder guiding technology, employer, and role search.
- **Form & state synchronization:** Wire the search input into the Ant Design Form and TanStack Query cache key in `react-app/src/requests/jobs.ts`, resetting pagination to page 1 whenever search terms change.
- **Empty state refinement (`react-app/src/pages/jobs/JobList.tsx`, `JobsPage.tsx`):** Provide contextual empty state messaging when zero results match a candidate's active keyword query `q`.
- **Applied jobs tab compatibility:** Ensure the applied applications tab and its bulk fetch pagination loop (`fetchAllJobFeedItems`) remain healthy and unaffected.
- **Frontend verification:** Ensure clean TypeScript compilation (`tsc -b`), linting (`eslint .`), and Vite production packaging (`vite build`).

### Out of scope

- Direct changes to backend Python API or OpenSearch queries (managed in the main repository via `hybrid-search-retrieval-eval-implementation-plan.md`).
- Corpus-wide unassessed job search (the user-facing UI strictly presents personalized, assessed opportunities per Q2).
- Autocomplete / live typeahead suggestions dropdown (deferred to a future UX iteration).
- Client-side regex text highlighting inside job description cards (can be added as an enhancement later).

---

## Codebase grounding

Frontend conventions and codebase layout (from `react-app/PROJECT_GUIDELINES.md`):

| Area | Location | What it means for this feature |
| --- | --- | --- |
| Query types | `react-app/src/types/jobs.ts:77-92` `JobFeedQuery` | Defines the API request payload. Must add optional `q?: string`. |
| Default queries | `react-app/src/types/jobs.ts:145-164` `DEFAULT_JOB_FEED_QUERY`, `APPLIED_JOBS_QUERY` | Default state objects. `DEFAULT_JOB_FEED_QUERY` keeps `q: undefined`. |
| Filter form | `react-app/src/pages/jobs/JobFilters.tsx:34-45` `FilterFormValues` | Form value interface. Must add `q?: string` and map bi-directionally in `queryToFormValues` and `formValuesToQuery`. |
| Filter UI layout | `react-app/src/pages/jobs/JobFilters.tsx:88-230` `JobFilters` | Currently renders a single collapsed `Collapse` panel ("Discovery filters"). A persistent search bar outside/above the collapse allows immediate keyword search without expanding filters. |
| Query hooks | `react-app/src/requests/jobs.ts:20-28` `unappliedJobFeedQueryKey` | TanStack Query cache key includes `params.query`. Adding `q` to `query` automatically triggers re-fetch on submission. |
| Feed request | `react-app/src/requests/jobs.ts:63-84` `useUnappliedJobFeed` | Posts `{ query, page, page_size }` to `/jobs/search`. Naturally forwards `q` once added to `JobFeedQuery`. |
| Page orchestrator | `react-app/src/pages/jobs/JobsPage.tsx:15-68` `JobsPage` | Holds `query` state, `unappliedPage`, and handlers `handleApplyFilters` / `handleResetFilters`. Resets page to 1 on apply. |
| Table / list view | `react-app/src/pages/jobs/JobList.tsx:21-48` `JobList` | Renders Ant Design `Table` of job cards. Displays `emptyTitle` and `emptyDescription` when `jobs.length === 0`. |

---

## Design

### 1. Search input UX & placement

Currently, `JobFilters` wraps all controls inside an Ant Design `Collapse` component (`defaultActiveKey={[]}`). If the search bar were placed inside the collapsible container, it would be hidden by default on initial page load, forcing candidates to expand filters before typing a keyword.

**Layout solution:**
Separate the search bar into an always-visible top bar, positioned directly above or integrated with the collapsible discovery filter drawer:

```tsx
<Flex vertical gap={12}>
  {/* Always-visible top search bar */}
  <Row gutter={[12, 12]} align="middle">
    <Col flex="auto">
      <Form.Item name="q" noStyle>
        <Input
          size="large"
          placeholder="Search matching jobs by technology, title, or employer (e.g. Python, Kubernetes, Stripe)..."
          prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
          allowClear
          onPressEnter={form.submit}
        />
      </Form.Item>
    </Col>
    <Col>
      <Button
        type="primary"
        size="large"
        icon={<SearchOutlined />}
        onClick={form.submit}
        loading={loading}
      >
        Search
      </Button>
    </Col>
  </Row>

  {/* Collapsible secondary structured filters */}
  <Collapse
    defaultActiveKey={[]}
    items={[
      {
        key: "filters",
        label: (
          <Flex align="center" gap={8} wrap="wrap">
            <FilterOutlined />
            <Typography.Text strong>Discovery filters</Typography.Text>
            <Typography.Text type="secondary">
              Score floors, locations, remote, and sources
            </Typography.Text>
          </Flex>
        ),
        children: (
          /* Structured filter controls: remote, location, scores, sources, etc. */
        ),
      },
    ]}
  />
</Flex>
```

### 2. Type definitions & contract mapping

In `react-app/src/types/jobs.ts`:

```typescript
export interface JobFeedQuery {
  q?: string;
  applied: boolean;
  remote?: boolean;
  sources: string[];
  tags: string[];
  location?: string;
  min_cv_ats_match_score?: number;
  min_profile_ats_match_score?: number;
  exclude_deal_breakers: boolean;
  exclude_skipped: boolean;
  application_stage?: ApplicationStage;
  active_only: boolean;
  sort_by: JobFeedSortField;
  sort_order: SortOrder;
}
```

In `react-app/src/pages/jobs/JobFilters.tsx`:

```typescript
interface FilterFormValues {
  q?: string;
  applied: boolean;
  remote?: "all" | "remote" | "onsite";
  sources?: string[];
  tags?: string[];
  location?: string;
  min_cv_ats_match_score?: number;
  min_profile_ats_match_score?: number;
  exclude_deal_breakers: boolean;
  show_skipped: boolean;
  sort_by: JobFeedSortField;
  sort_order: SortOrder;
}

function queryToFormValues(query: JobFeedQuery): FilterFormValues {
  return {
    q: query.q,
    applied: query.applied,
    // ... remaining existing mappings
  };
}

function formValuesToQuery(values: FilterFormValues): JobFeedQuery {
  const trimmedQ = values.q?.trim();
  return {
    q: trimmedQ && trimmedQ.length > 0 ? trimmedQ : undefined,
    applied: values.applied,
    // ... remaining existing mappings
  };
}
```

### 3. State management & pagination

- **Submit on Enter / Button Click:** When the user presses Enter in the search input or clicks "Search" / "Apply filters", `form.submit` triggers `onFinish`.
- **Automatic page reset:** `handleApplyFilters` in `JobsPage.tsx` sets `query` to `nextQuery` and explicitly calls `setUnappliedPage(1)`.
- **Clear button behavior:** When the user clicks the clear (`x`) button on `Input allowClear`, if submitted or cleared, `formValuesToQuery` maps `q` to `undefined`, restoring the full feed.
- **TanStack Query caching:** `unappliedJobFeedQueryKey(params)` includes `params.query`. Because `query.q` becomes part of this key, TanStack Query automatically manages caching, loading indicators (`isFetching`), and updates without stale state collisions.

### 4. Contextual empty state feedback

When a user searches for a specific technology (e.g. `"Rust"`), if no assessed jobs match that keyword combined with their ATS filters, the current generic empty state ("No jobs available") can confuse users into thinking the system is broken.

In `react-app/src/pages/jobs/JobsPage.tsx`:

```tsx
<JobList
  listKey={activePanel}
  jobs={unappliedFeed.jobs}
  total={unappliedFeed.total}
  page={unappliedFeed.page}
  pageSize={unappliedFeed.pageSize}
  loading={unappliedFeed.isFetching}
  filterContext={unappliedContext}
  onPageChange={handleUnappliedPageChange}
  emptyTitle={
    query.q
      ? `No jobs found matching "${query.q}"`
      : "No new opportunities found"
  }
  emptyDescription={
    query.q
      ? "Try searching for a different technology, title, or employer, or lower the ATS match threshold."
      : "Try adjusting your discovery filters or check back after the next scheduled ingestion cycle."
  }
  allowSkip
/>
```

### 5. Applied applications tab interaction

- `APPLIED_JOBS_QUERY` in `react-app/src/types/jobs.ts` does not set `q`.
- `useAppliedJobFeed` in `react-app/src/requests/jobs.ts` continues calling `fetchAllJobFeedItems(APPLIED_JOBS_QUERY)` for client-side window filtering (`postedWithinDays`).
- Keyword search is specifically enabled for the `unapplied` ("New opportunities") tab where candidates discover matching jobs.

---

## Implementation phases

### Phase 1 — Type updates & request layer

**Reviewable when:** `JobFeedQuery` and `FilterFormValues` accept `q?: string`; `yarn tsc -b` compiles cleanly without errors.
**Touches:** `react-app/src/types/jobs.ts`, `react-app/src/requests/jobs.ts`

- Add `q?: string` to `JobFeedQuery` in `src/types/jobs.ts`.
- Ensure `DEFAULT_JOB_FEED_QUERY` and `APPLIED_JOBS_QUERY` remain type-valid.
- Verify `useUnappliedJobFeed` forwards `q` cleanly to `apiClient.post("/jobs/search")`.

### Phase 2 — `JobFilters` component integration

**Reviewable when:** Persistent search input appears above the discovery filters collapse; typing text and pressing Enter or clicking Search triggers `onApply` with `q: "..."`; clicking Reset clears `q` back to `undefined`.
**Touches:** `react-app/src/pages/jobs/JobFilters.tsx`

- Update `FilterFormValues`, `queryToFormValues`, and `formValuesToQuery` to handle `q`.
- Add the search input row with `<SearchOutlined />` prefix, placeholder text, and `allowClear`.
- Ensure `onReset` resets the form fields including `q`.

### Phase 3 — Contextual empty states & UX polish

**Reviewable when:** Searching for a non-existent keyword displays the contextual empty title and description with the query term reflected; clearing the search restores the full unapplied list.
**Touches:** `react-app/src/pages/jobs/JobsPage.tsx`

- Dynamically populate `emptyTitle` and `emptyDescription` on `JobList` based on whether `query.q` is present.
- Verify that changing search input automatically resets active page to 1.

### Phase 4 — Production build & end-to-end verification

**Reviewable when:** `yarn lint` and `yarn build` pass without warnings/errors; running against a running backend API validates that keyword queries return matching assessed jobs.
**Touches:** `react-app/` package build scripts.

- Run `npm run lint` / `yarn lint` to verify ESLint compliance.
- Run `npm run build` / `yarn build` to verify Vite bundle output.
- Manually verify against the running backend with seeded test jobs (e.g. searching for `"Python"` returns only Python postings with ATS scores).
