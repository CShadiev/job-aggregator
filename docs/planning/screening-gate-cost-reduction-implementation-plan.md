# Screening Gate Cost Reduction — Implementation Plan

**Status:** Ready for implementation
**Last updated:** 2026-09-15
**Open questions:** 0
**Origin:** Surfaced by "The headline arithmetic, as it actually computes" in [`readme-landing-page-and-evals-showcase-implementation-plan.md`](readme-landing-page-and-evals-showcase-implementation-plan.md). That plan is blocked on this one: its Q1 asks which cost claim goes above the fold, and the honest single-gate answer today is a negative number.

Status values: `Draft` (kickoff done, questions open) · `In deliberation` (some decisions recorded, questions remain) · `Ready for implementation` (no open questions, consistency pass done) · `Implemented` (shipped).

---

## Problem

The project's headline architectural claim is a cost-gating pipeline: a cheap screening pass drops obvious non-fits before expensive fit assessment. **That gate currently loses money in production.**

From the last pipeline cycle: 300 pairs screened for $0.41, 145 survivors assessed for $0.34, total $0.75. Assessing all 300 outright would have cost about $0.70. The gate costs roughly 6.6% extra per cycle to have. The committed benchmark's 23% saving is the best case, not the live case.

The economics reduce to one identity. Per pair, ungated spend is one assessment call; gated spend is every screen plus the surviving assessments. So:

```
saving = r − ρ        r = reduction rate,  ρ = screening cost per call ÷ assessment cost per call
```

The gate breaks even at `ρ = r`. Every number below is an instance of that identity:

| Configuration | r | ρ | saving |
| --- | --- | --- | --- |
| Pre-`f854085`, assessment on `grok-4.3` | 0.640 | 0.038 | **+60.2%** |
| Committed benchmark, assessment on `gpt-5-mini` | 0.640 | 0.411 | **+22.9%** |
| Production last cycle, post-retrieval | 0.517 | 0.583 | **−6.6%** |

**The gate did not regress; its dividend did.** Before commit `f854085` the model factory registered only `grok-4.3` and `grok-4.5` at $3.00/$15.00 per 1M, so assessment cost $0.0336 per call and the gate removed genuinely expensive work. That commit introduced `gpt-5.6-luna` and `gpt-5-mini` together and moved assessment onto `gpt-5-mini`, roughly 11× cheaper. The screener still drops 64% of pairs at 0.967 Good Recall — the work it removes simply stopped being worth removing.

Two further facts make this fixable rather than merely disappointing:

- **82% of screening input is byte-identical on every call.** Across the 300 calls in `benchmarks/screening/reports/20260909_115647_gpt-5.6-luna.results.jsonl`, minimum input is 4,714 tokens and mean is 5,739. The floor is the CV PDF plus instructions; only ~1,025 tokens vary per job. Input is ~90% of screening spend.
- **That constant block is positioned so it can never be cached.** `agents/screening.py:36-40` sends `[job_prompt, cv]` — variable first, constant last. Prefix caching keys on leading bytes.

So the cheapest wins are packaging, not model choice. Fixing the CV representation and the content ordering plausibly takes the published claim from 23% to roughly 50% **on the model already in production**, with no recall risk from a weaker model. A cheaper screener then pushes it past 60%.

## Scope

### In scope

- Reduce screening cost per call by changing how the CV and instructions are packaged: the CV becomes an LLM-generated layout-faithful text rendering (Q2, decided), and constant content moves ahead of the variable job payload so the prefix is cacheable.
- Teach the cost model about cached tokens so the change is measurable at all (Q4).
- Wire a cheaper model provider and register candidate screening models (Q6).
- Run the screening benchmark across candidates and pick one on a cost-to-recall basis against a pre-agreed recall floor (Q7).
- Publish the `saving = r − ρ` framing and the resulting numbers as the input to the README plan's Q1.

### Out of scope

- Any README or `docs/evals.md` prose. This plan produces the numbers; the other plan publishes them.
- Fit-assessment *quality* work, prompt rewrites for accuracy, and the retrieval gate's ratio. Fit-assessment *packaging* is in scope — Q3 decided both agents get the CV-text substitution and the reordering.
- The dataset privacy question — that is the README plan's Q3 and is independent.
- Changing the gold labels or the screening dataset's composition. The 300-entry 30/60/210 stratification stays fixed so runs remain comparable.

## Codebase grounding

| Area | Location | What it means for this feature |
| --- | --- | --- |
| Screening agent content order | `agents/screening.py:36-40` | `user_content = [prompt, self._cv_content(cv)]`. Variable job payload precedes the constant CV. This single ordering is what makes the 4,714-token prefix uncacheable. |
| Screening prompt shape | `agents/prompt_templates/screening.md` | `{job_posting}` sits at line 30 with `## IMPORTANT NOTES` after it. To get a maximal stable prefix the job payload must move to the very end, so the template needs splitting into a constant prefix and a variable suffix — not just a swap of the two list elements. |
| Fit assessment is identical | `agents/fit_assessment.py:69-72`, `102-106` | Same `[prompt, cv]` ordering, same PDF `BinaryContent`. 9,290 input tokens per call. Q3 decided the same treatment applies here, which cuts total spend while lowering the gate's percentage contribution because assessment cost is ρ's denominator. |
| Cache tokens are already reported | `pydantic_ai.usage.RequestUsage` | Exposes `cache_read_tokens` and `cache_write_tokens` alongside `input_tokens`. The data needed to verify a cache hit is already flowing through `result.usage()` and is currently discarded. |
| Cost model cannot express caching | `monitoring/pricing.py:27-31`, `90-95` | `ModelRate` has only `input_usd_per_1m` and `output_usd_per_1m`; `estimate_cost_usd` takes two token counts. There is no cached-input rate anywhere. |
| Production accounting ignores cache | `monitoring/metrics.py:180-183` | `record_agent_usage` reads only `input_tokens` / `output_tokens`. A caching change would not move the Grafana cost panels or the benchmark's cost line — it would be invisible. This must land before, or with, the packaging change. |
| Benchmark cost is the same code path | `scripts/run_screening_benchmark.py:245-249` | `_estimate_run_cost` uses static `DEFAULT_RATES` and reports `$0` for any model not in it. A new candidate model with no rate card silently benchmarks as free. |
| Benchmark drops cache counts | `models/screening.py:19-25`, `agents/screening.py:51-56` | `ScreeningResult` carries `input_tokens` / `output_tokens` only, so `EntryResult` and `.results.jsonl` cannot record cache hits either. |
| Model registry is a closed enum | `agents/model_factory.py:19-38`, `scripts/run_screening_benchmark.py:126-132` | Four models: `grok-4.3`, `grok-4.5` ($3.00/$15.00), `gpt-5.6-luna` ($0.20/$1.20), `gpt-5-mini` ($0.25/$2.00). `_parse_model` validates `--model` against the enum. **Every registered alternative is more expensive than what screening already runs**, so the benchmark cannot be pointed at a cheaper model without a registry change. |
| DeepInfra is half-wired | `config.py:60`, `.github/workflows/ci.yml:19`, `README.md:279` | `DEEPINFRA_API_KEY: str` is required with no default, so no process starts without it, and CI injects a mock. But `model_factory.py` has no DeepInfra provider. Every deployment carries a mandatory credential for a provider that is never used. It is an OpenAI-compatible endpoint, so `OpenAIProvider(base_url=...)` is the same shape as the existing `GROK_PROVIDER`. |
| No PDF text extraction exists | `pyproject.toml:7-31` | No `pypdf`, `pdfplumber`, or `pdfminer`. `fpdf2` is present but it *writes* PDFs. Q2 chose LLM extraction over adding a parser, so this stays true — the feature adds **no new dependency**. |
| An LLM CV-extraction precedent exists | `scripts/generate_gating_benchmark_dataset.py:59-78` | Already extracts a structured `UserProfile` from `cv.pdf` via a PydanticAI agent with `BinaryContent.from_path`, and caches the result to disk. Precedent for a one-time offline CV→structured conversion. |
| A structured profile already exists in Mongo | `models/users.py:153-174`, `search/text.py:27-49` | `UserProfile` carries summary, skills, experience, education, certifications. `flatten_profile()` already renders it to a single text string for embedding and BM25. This is a zero-dependency source of CV-equivalent text — but it is not the CV, which is why Q2 rejected it. Still relevant as the shape to follow for rendering structured data to prompt text. |
| Screening's prompt forbids profile data | `agents/prompt_templates/screening.md:11,36` | "Do **not** invent or rely on any user profile beyond what is evidenced on the CV" and "Ignore any implied profile information that is not on the CV." Substituting `UserProfile` for the CV contradicts the prompt's own contract and the gold labels' provenance — the reason Q2 rejected that option. It also sets the fidelity bar the Q2 extraction must clear: the rendering has to remain recognisably *the CV*, which is what Q9 verifies. |
| Screening dataset has no profile | `scripts/run_screening_benchmark.py:99-107`, `scripts/export_screening_benchmark_dataset.py:183-199` | The dataset is `manifest.json` + `entries.jsonl` + `cv.pdf`. Deliberately no `profile.json` — the archived plan notes it as "unused by agent". Any profile-based option requires a dataset re-export. |
| **There is no CV upload path** | `repository/object_storage.py:150-162`, `api/routes/` | `upload_user_cv` is defined and **never called** from application code, and there is no CV or profile endpoint anywhere (`api/routes/users.py` has only `/login` and `/refresh`). CVs reach S3 out of band. So there is no upload event to hook a "regenerate on new CV" trigger onto — freshness must be evaluated lazily on read. Directly shapes Q2's freshness contract and Q10. |
| **The profile is read-only** | `repository/mongo_jobs_repository.py:85,338-355` | `_user_profiles` supports only `find()` and `find_one()`. There is **no write path to `user_profiles` at all**. Persisting anything onto the profile means creating the first one. The archived retrieval plan hit this same wall (`docs/planning/archive/hybrid-search-retrieval-eval-implementation-plan.md:72`: "**No profile write API**") and resolved it by *not* persisting — an in-memory content-hash cache instead. |
| Three agents dump the whole profile | `agents/fit_assessment.py:91`, `agents/cover_letter_generation.py:72` | Both call `user_profile.model_dump_json(indent=2)`. **Any field added to the `UserProfile` model is automatically injected into the fit-assessment and cover-letter prompts.** Fit assessment also attaches the CV PDF, so it would carry the CV twice and its input tokens would *grow*. This is the central constraint on where the extracted text lives — see Q8 — and it collides with Q3. |
| Embeddings are safe from a new field | `search/text.py:27-49`, `search/embeddings.py:64-80` | `flatten_profile` enumerates fields explicitly rather than dumping the model, so a new profile field does **not** enter the embedding text, does not change `profile_text_hash`, and cannot invalidate the committed retrieval corpora or `baseline.json`. |
| Content-hash freshness precedent | `search/embeddings.py:64-80`, `search/text.py:52-54` | `embed_profile` is the existing shape for a derived artifact keyed by a content digest: flatten → SHA-256 → module-level dict cache → compute on miss, with `clear_profile_embedding_cache()` for tests. Q2's PDF-hash contract is the same pattern with a persistent store instead of a dict. |
| The CV is re-fetched per pair | `orchestration/nodes/pair.py:77`, `109` | `object_storage.get_user_cv(username)` is a synchronous boto3 `get_object` called inside `screen()` and again inside `assess()`, once per pair — roughly 300 S3 downloads of the same PDF per cycle today, uncached. Whatever computes or validates the CV text must not inherit that call pattern. See Q10. |
| Production r ≠ benchmark r | `orchestration/nodes/batch.py:247-249`, `config.py:98` | Pairs are built from the retrieval top-K, then screened. At `PIPELINE_RETRIEVAL_RATIO = 0.5` the 300 screened pairs are the top half of a ~600-job batch — a higher-fit distribution where the drop rate falls to 51.7% against the benchmark's 64.0%. The benchmark measures the full corpus. See Q5. |

### Measured token profile

Screening, from the committed 300-call run:

| Quantity | Value |
| --- | --- |
| Input tokens, min / mean / max | 4,714 / 5,739 / 7,380 |
| Constant prefix (= min) | 4,714 tokens — CV PDF + instructions |
| Variable per-job payload (mean above floor) | ~1,025 tokens |
| Output tokens, mean | 101.6 |
| Cost per call at `gpt-5.6-luna` | $0.001270 |

Fit assessment, from `benchmarks/fit_assessment/reports/20260909_173301_gpt-5.6-luna.md`: 9,290 input / 383 output per call, which is $0.003089 at `gpt-5-mini` rates.

### The envelope a replacement model must hit

Holding r at 0.640 and assessment at $0.003089 per call:

| Headline saving | Required ρ | Screening $/call | vs today | Implied input rate $/1M |
| --- | --- | --- | --- | --- |
| 40% | 0.240 | $0.000741 | 1.7× cheaper | $0.098 |
| 50% | 0.140 | $0.000432 | 2.9× cheaper | $0.057 |
| 55% | 0.090 | $0.000278 | 4.6× cheaper | $0.037 |
| 60% | 0.040 | $0.000124 | 10.3× cheaper | $0.016 |

The implied input rate assumes today's PDF packaging and that input stays ~90% of screening spend. **Fix the packaging first and every row gets substantially easier** — which is why Q1 was decided the way it was.

## Design

### CV text extraction

Decided in Q2: an LLM converts `cv.pdf` into a text representation that preserves layout-derived signal (section boundaries, ordering, emphasis, grouping) rather than just concatenating glyphs, and the result is cached against a hash of the source PDF so a replaced CV invalidates it.

Settled independent of the open sub-questions:

- **The extraction agent follows the existing precedent.** `scripts/generate_gating_benchmark_dataset.py:59-78` already builds a PydanticAI `Agent` with `BinaryContent.from_path(cv_path)` and a structured `output_type`, caches the result to disk, and takes a `--force` flag to re-extract. The new agent is the same shape with a text-oriented output type.
- **The extraction prompt is a fidelity contract, not a summarizer.** The word "summary" is a trap here: anything that compresses content changes what the screener sees and moves recall for reasons unrelated to packaging. The output should be a lossless-in-content, layout-annotated rendering — headings preserved as headings, chronology preserved, bullet grouping preserved, nothing paraphrased away. Q9 covers how that gets verified rather than assumed.
- **The freshness key is a digest of the PDF bytes.** `ObjectStorage.get_object_bytes` already returns the raw bytes, so `hashlib.sha256(cv_bytes).hexdigest()` needs no new S3 call beyond the one already being made. Storing the digest alongside the text is what makes staleness detectable; an S3 ETag is not a safe substitute because multipart uploads make it a non-digest.
- **Extraction cost is negligible and amortized.** One call per CV per change: roughly 4,714 input tokens and perhaps 1,000–1,500 output, about $0.003 at `gpt-5.6-luna` rates. Each screening call it enables saves about $0.00076, so it repays itself after about four screenings and then compounds across every cycle.

Settled by Q8, Q9 and Q10: the rendering and its digest live on the `user_profiles` document but **not** on the `UserProfile` model, read through a narrow model and a dedicated repository method so nothing can leak into the fit-assessment or cover-letter prompts. The freshness check runs once per candidate per cycle in `build_pairs`, beside the existing profile embedding, with the text threaded through `PairState` to both `screen()` and `assess()`. Fidelity is confirmed by a one-time manual read of the rendering against `cv.pdf` before the isolated benchmark run.

### Isolating the recall effect

Decided in Q2: the CV-text substitution is benchmarked **on its own**, before any reordering or model change, so the recall delta is attributable.

This is cleanly possible and cheaper than it looks:

- The comparison baseline already exists — `benchmarks/screening/reports/20260909_115647_gpt-5.6-luna.md` is the same 300 entries, the same gold labels, the same model, at t=0.0.
- The run needs **no dataset re-export**. Adding a generated CV-text artifact beside the existing `cv.pdf` in `benchmarks/screening/dataset/05082026/` leaves `entries.jsonl`, `manifest.json` and the 30/60/210 stratification untouched, so the two reports stay directly comparable. `cv.pdf` must stay in place regardless: `benchmarks/retrieval/dataset/*/manifest.json` references it as `source.cv_path`.
- It does **not** depend on the cache accounting work (Phase 2 / Q4). This change reduces token *count*, not token price, so the effect is fully visible through the existing `input_tokens` accounting. Cached-token support is only needed for the reordering change.

The comparison to record: input tokens per call, cost per 100, Reduction Rate, Good Recall and Fitting Recall, before and after, on `gpt-5.6-luna`. Q7's floor is what the "after" column has to clear.

### Prompt packaging

Q3 decided that fit assessment gets the same treatment as screening, so both `agents/screening.py` and `agents/fit_assessment.py` are in scope. The target content order is *constant, then variable* — instruction prefix, CV, then job payload last. Reaching it requires splitting `screening.md` at the `{job_posting}` placeholder so the trailing `## IMPORTANT NOTES` block moves into the constant prefix, then assembling `[prefix, cv_content, job_suffix]`. Swapping the two elements of the existing list is not sufficient and would leave `## IMPORTANT NOTES` stranded after the variable payload.

Reordering is not semantically neutral even though the content is identical: models weight position, so recall must be re-measured rather than assumed. That is what the harness is for.

### Cost accounting for cached tokens

Decided in Q4: `cached_input_usd_per_1m` joins `ModelRate`, `DEFAULT_RATES` and the Mongo `pricing` documents, and `cache_read_tokens` is threaded through `estimate_cost_usd`, `record_agent_usage`, `ScreeningResult` and `EntryResult`. Without that path, a caching win cannot appear in either the benchmark's cost line or the Grafana cost panels — the change would look like a no-op in exactly the artifacts this project uses to prove things.

The arithmetic is `(input − cache_read) × input_rate + cache_read × cached_rate`, because `input_tokens` includes cached tokens on OpenAI-compatible providers. Getting this backwards double-counts the prefix. An absent cached rate falls back to the full input rate, so an unproven discount never inflates a published number.

`ScreeningResult` and `EntryResult` also need `cache_read_tokens` so `.results.jsonl` records whether a run actually hit cache. Without it a run that silently stopped caching would look like a pricing regression with no way to tell.

### Benchmark and model registry

Decided in Q6: a `DEEPINFRA_PROVIDER` is added following the `GROK_PROVIDER` pattern, each candidate gets a `Model` enum member and a `DEFAULT_RATES` entry, and an unpriced model becomes a **hard failure** of `run_screening_benchmark.py` rather than a `$0.00` line in an otherwise complete report. Two mechanical constraints drive that: `_parse_model` rejects anything outside the enum, and `_estimate_run_cost` currently reports `$0.00` for any model absent from `DEFAULT_RATES` while still printing the full report — the most dangerous possible failure mode for a plan whose entire output is a cost number.

### Candidate economics, provisional

Computed from the Q6 rate cards and the measured token profile, with unspecified cached rates modelled at the full input rate per Q4. Screening cost per call:

| Model | PDF, no cache | PDF, cached | Text CV, no cache | Text CV, cached |
| --- | --- | --- | --- | --- |
| `gpt-5.6-luna` | $0.001270 | $0.000421 | $0.000507 | $0.000345 |
| `gpt-oss-120b` | $0.000230 | $0.000230 | $0.000088 | $0.000088 |
| `gpt-oss-120b-turbo` | $0.000922 | $0.000922 | $0.000350 | $0.000350 |
| `glm-5.3-flash` | $0.000912 | $0.000346 | $0.000340 | $0.000232 |

Saving at the text-CV endpoint, against a fit assessment also on text CV ($0.002135/call per Q3), at the benchmark's r = 0.640 and at the production-observed r = 0.517:

| Model | r = 0.640, cached | r = 0.517, cached |
| --- | --- | --- |
| `gpt-5.6-luna` | 47.8% | 35.5% |
| `gpt-oss-120b` | **59.9%** | **47.6%** |
| `gpt-oss-120b-turbo` | 47.6% | 35.3% |
| `glm-5.3-flash` | 53.2% | 40.9% |

Two observations worth carrying into Phase 5. First, **`gpt-oss-120b` is a larger lever than the packaging work**: at $0.037 / $0.17 it reaches 56.6% saving with *no* packaging change at all, against luna's 22.9% today. That revises the earlier working assumption that packaging dominated model choice — it was true against a 3–4× cheaper model, not against a 5.4×-input / 7×-output one. Second, **prefix caching cannot rescue an expensive model here**, because only the ~4,714-token constant prefix is cacheable while the ~1,025-token job payload is always fresh: luna with a cached prefix ($0.000345) is still 3.9× more expensive per call than `gpt-oss-120b` with no caching at all ($0.000088). All of these numbers are cost-only and carry no recall information; Q7's floor is what decides whether the cheapest candidate is admissible.

### What gets published

The `saving = r − ρ` identity, the token profile that motivated the packaging change, and a candidate comparison table. The comparison table is the artifact that makes the eval loop look real: it shows a decision being made from measurements rather than asserted. This feeds the README plan's Q1 and its `docs/evals.md` "what the benchmarks decided" section.

## Open questions

None. All 10 questions resolved; see Decision log below.

## Decision log

### Q7 — Dual recall floors at Good Recall ≥ 0.900 and Fitting Recall ≥ 0.800 with committed regression baseline

**Decided:** 2026-09-15
Enforce dual acceptance floors for any candidate model or prompt packaging change: **Good Recall ≥ 0.900** (allowing at most 3 misses out of 30) and **Fitting Recall ≥ 0.800** (allowing at most 18 misses out of 90). The chosen production model will have its metrics frozen in `benchmarks/screening/dataset/<version>/baseline.json` with a CI regression test mirroring retrieval (`test_retrieval_smoke.py`).

**Rejected:** *Good Recall floor of 0.933* — rejected because 0.933 sits well inside the 95% Wilson confidence interval [0.833, 0.994] at n=30, meaning it would reject candidate models on statistical noise. *Good-only floor (option c)* — rejected because Good Recall (n=30, 3.33 pp/item) is coarse, while Fitting Recall (n=90, 1.11 pp/item) is a 3× finer instrument that detects genuine degradation before Good Recall can resolve it. A candidate could hold Good Recall at 29/30 by luck while collapsing Fitting from 78/90 to 60/90; pairing the two prevents this at zero cost.

**Consequence:** Candidate models in Phase 5 must clear both floors. Phase 6 writes the screening `baseline.json` and smoke test.

### Q5 — Reduction rate is framed parameterically; benchmark reports intrinsic rates and sensitivity range

**Decided:** 2026-09-15
Do not treat reduction rate ($r$) as an intrinsic static model property or a single fragile percentage. The benchmark keeps its reference 300-job stratified dataset (30 good / 60 moderate / 210 low) to measure the screener's true capabilities: low-tier junk rejection rate ($\text{TNR}_{\text{low}} = 85.7\%$), Good Recall, and Fitting Recall, plus screening cost per call $x$. Downstream fit assessment cost per posting $p_2$ is surfaced as an explicit external parameter (e.g. $p_2 = \$0.002135$ with text CV on `gpt-5-mini`).

Net pipeline savings are calculated parameterically as $\text{Saving} \approx (1 - p_1) \times \text{TNR}_{\text{low}} - x / p_2$ across a stated sensitivity matrix of feed compositions ($p_1$: fraction of fitting jobs), alongside the break-even threshold $\text{Junk}_{\text{min}} = (x/p_2) / \text{TNR}_{\text{low}}$.

**Rejected:** *Replaying on a post-retrieval subset only* — hides the intrinsic screener performance behind one specific retrieval threshold. *Headlining a single empirical reduction rate* — falsely implies $r$ is constant, when in reality $r$ drops naturally as upstream retrieval cleans the incoming feed.

**Consequence:** The benchmark harness report and README plan headline report the cost ratio $\rho = x / p_2$, the break-even junk threshold (e.g. $\sim 4.8\%$ for `gpt-oss-120b`), and a sensitivity table (e.g. reference mix 56%, production post-retrieval mix 41%, clean mix 30%) instead of a brittle single number.

### Q6 — DeepInfra is wired as a provider and each candidate gets an enum member, with unpriced models failing the benchmark

**Decided:** 2026-09-14
Add a `DEEPINFRA_PROVIDER` using the existing `OpenAIProvider(api_key=..., base_url=...)` pattern from `GROK_PROVIDER`, and register one `Model` enum member per candidate. The unpriced-model guard is adopted as mandatory: a model in the enum but absent from `DEFAULT_RATES` must make `run_screening_benchmark.py` exit non-zero rather than print a report showing `$0.00`.

Candidate shortlist and rate cards (USD per 1M; input / cached input / output):

| Model | Host | Input | Cached input | Output |
| --- | --- | --- | --- | --- |
| `gpt-5.6-luna` | OpenAI | 0.20 | 0.02 | 1.20 |
| `gpt-oss-120b` | DeepInfra | 0.037 | unspecified | 0.17 |
| `gpt-oss-120b-turbo` | DeepInfra | 0.15 | unspecified | 0.60 |
| `glm-5.3-flash` | DeepInfra | 0.15 | 0.03 | 0.50 |

Per Q4's conservative fallback, the two `unspecified` cached rates are modelled at the **full input rate**, not zero — an absent cached price is treated as "no caching discount proven" rather than "caching is free".

**Rejected:** *Runtime `provider:model` strings* — more flexible, but loses the closed-set guarantee behind `_parse_model`'s error message and weakens the coupling to `DEFAULT_RATES` that the unpriced guard depends on. *Benchmark-only escape hatch with `--input-rate` flags* — unnecessary at a four-model shortlist, and rates passed on the command line do not end up in the committed report where a reader can check them.

**Consequence:** `DEEPINFRA_API_KEY` stops being a mandatory-but-unused credential. Two risks to verify during Phase 5 rather than assume: `ScreeningAgentOutput` requires structured output (`worth_full_assessment: Literal[0,1]` plus a bounded float), and open-weight models behind an OpenAI-compatible shim vary in schema-enforcement fidelity — `_FAILURE_ABORT_RATIO = 0.20` is the existing guard that would catch a model unable to comply. Provisional economics are in the candidate table under Design.

### Q4 — Cached tokens become a first-class rate, with a conservative fallback

**Decided:** 2026-09-14
Add `cached_input_usd_per_1m` to `ModelRate`, `DEFAULT_RATES` and the Mongo `pricing` documents, and thread `cache_read_tokens` through `estimate_cost_usd`, `record_agent_usage`, `ScreeningResult` and `EntryResult`. The field is defaulted so existing pricing documents keep validating, and **an absent cached rate falls back to the full input rate**, not to zero — an unproven discount understates the win rather than overstating a published number.

**Rejected:** *Treat cached reads as free* — overstates the saving by exactly the cached rate, unacceptable when the deliverable is a cost claim. *Report token deltas only and compute dollars by hand* — avoids the schema change but leaves the Grafana cost panels wrong, which is worse given the dashboard is itself a publishing target in the README plan.

**Consequence:** the cost arithmetic becomes `(input − cache_read) × input_rate + cache_read × cached_rate`, because `input_tokens` includes cached tokens on OpenAI-compatible providers. Getting that wrong double-counts the prefix. Applies to all four agents, not just screening.

### Q3 — Both agents get the packaging fix, and the published headline changes shape

**Decided:** 2026-09-14
Apply the CV-text substitution and the content reordering to fit assessment as well as screening, accepting the lower gate-attributable percentage, and report the result honestly rather than protecting the ratio.

**Rejected:** *Fix screening only* — optimizing the metric instead of the product, and indefensible the moment a reader diffs the two agents and finds the same defect fixed in one of them. *Fix both but reframe the headline away from a percentage* (the original leaning) — not rejected in substance so much as deferred: it overlaps the README plan's Q1 and this plan's Q5, both of which are converging on reporting the `r − ρ` decomposition and per-band rates rather than a single percentage. Recorded here so the framing decision is made once, in Q5, rather than twice.

**Consequence:** total pipeline spend falls further while the gate's percentage contribution falls with it — roughly $0.383 versus $0.486 per 300-pair batch, at ~40% versus ~48% gate-attributable saving. Fit assessment needs the CV text in `assess()`, which is why Q10 threads it through `PairState` rather than resolving it inside `screen()`.

### Q10 — The freshness check runs once per cycle in `build_pairs`

**Decided:** 2026-09-14
Fetch the CV, hash it, and regenerate the text if the digest moved, once per candidate per cycle in `build_pairs` — beside the existing profile embedding — then thread the text through `PairState` to both `screen()` and `assess()`.

**Rejected:** *Lazy check in `screen()` with a process-level cache* — smaller diff, but risks concurrent pairs racing into duplicate extractions at `PIPELINE_PAIR_CONCURRENCY = 10` and leaves `assess()` re-fetching, which Q3 makes untenable. *Manual maintenance script* — turns "always fresh" into an operational promise rather than a guarantee. *Backfill inside the repository layer* — hides an LLM call inside a data-access method.

**Consequence:** retires the existing pattern where `object_storage.get_user_cv` is called once per pair in both `screen()` and `assess()` (`orchestration/nodes/pair.py:77,109`) — roughly 300 redundant S3 downloads of the same PDF per cycle. `PairState` gains a field, so `orchestration/state.py` and the checkpointer's serialized state shape change.

### Q9 — Fidelity is verified by human review of the one CV

**Decided:** 2026-09-14
Read the generated rendering against `cv.pdf` once, manually, before the isolated benchmark run. There is exactly one CV in play for both production and the dataset, so this is minutes of work and the highest-confidence check available.

**Rejected:** *Structural assertion set* — not rejected permanently, but premature at one CV; revisit if the extraction becomes a self-serve path with real users. *Extract twice and diff* — measures stability, not fidelity. *Let the benchmark be the judge* — explicitly rejected: it conflates extraction quality with the quantity being measured, so a lossy extraction and a genuine text-versus-PDF recall effect would be indistinguishable in the report, defeating the isolation Q2 exists to provide.

**Consequence:** Phase 1a is not reviewable until the review has happened and been recorded. If the rendering cannot be made faithful, Q2's fallback applies — keep the PDF and take the reordering win alone.

### Q8 — The CV text lives on the `user_profiles` document but not on the `UserProfile` model

**Decided:** 2026-09-14
Store the rendering and its source digest in the same `user_profiles` document, and read them through a separate narrow model and repository method rather than adding fields to `UserProfile`.

**Rejected:** *Fields on `UserProfile` with `exclude=` at the dump sites* — works today and fails silently tomorrow. `agents/fit_assessment.py:91` and `agents/cover_letter_generation.py:72` both call `model_dump_json(indent=2)`, so correctness would depend on every present and future profile-dumping call site remembering to exclude; the failure mode is an unexplained cost regression, and fit assessment would carry the CV twice. *A separate `cv_texts` collection* — cleaner isolation but a second document to keep consistent with the profile and a new collection constant. *S3 beside `cv.pdf`* — no Mongo write path needed, but least queryable and it would put the read on the per-pair object-storage path.

**Consequence:** creates the **first write path to `user_profiles`** — the collection is currently read-only (`find` / `find_one` only, `repository/mongo_jobs_repository.py:338-355`). `UserProfile` keeps its current meaning as exactly the prompt payload, so the auto-injection hazard becomes structurally impossible rather than a rule to remember. This diverges deliberately from the precedent in `docs/planning/archive/hybrid-search-retrieval-eval-implementation-plan.md:72`, which faced the same missing write path and chose an in-memory content-hash cache instead; persistence is justified here because the API and worker are separate processes and the rendering is expensive enough to be worth surviving a restart.

### Q2 — The CV becomes an LLM-generated, layout-faithful text rendering, cached against the PDF's hash

**Decided:** 2026-09-14
An LLM converts `cv.pdf` into a text representation that preserves not only the text content but the layout-derived signal — section structure, ordering, grouping, emphasis. The rendering is stored with the candidate's profile data and keyed to a digest of the source PDF, so replacing the CV invalidates the rendering and it is regenerated rather than served stale. Screening then receives this text instead of the PDF attachment.

The screening benchmark is run with **this change in isolation**, before any content reordering or model substitution, so the recall delta is attributable to the CV representation alone. The comparison baseline is `benchmarks/screening/reports/20260909_115647_gpt-5.6-luna.md` — same 300 entries, same gold labels, same model.

**Rejected:** *Parser-based text extraction* (`pypdf` / `pdfplumber`) — adds a dependency and, more importantly, is the option least able to meet the layout-fidelity requirement: parsers emit reading-order glyphs and mangle the multi-column and sidebar layouts that CVs actually use. *Rendering the existing `UserProfile`* — zero-cost and already in Mongo, but it contradicts `agents/prompt_templates/screening.md:11,36` ("ignore any implied profile information that is not on the CV"), turns screening into profile matching wearing a CV-screening prompt, and would make the reported recall mean something different from what the gold labels certify. *Keeping the PDF and fixing ordering only* — lowest risk but leaves the 4,714-token floor in place and buys nothing at all if the provider declines to cache file content; it is retained as the fallback if Q9 finds the extraction cannot be made faithful.

**Consequence:** the extraction is a new production code path, not just a benchmark fixture — the CV text has to exist for the pipeline's `screen()` node too, which spawned Q8 (where it is persisted, given that a `UserProfile` field auto-injects into the fit-assessment and cover-letter prompts), Q9 (how fidelity is verified rather than asserted) and Q10 (where the freshness check runs, given there is no CV upload event to hook). The isolated benchmark run does **not** depend on Q4, because reducing token count is visible through existing `input_tokens` accounting; only the reordering change needs cached-token support. `cv.pdf` stays in the dataset directory regardless, since `benchmarks/retrieval/dataset/*/manifest.json` references it as `source.cv_path`.

### Q1 — Packaging fixes land before model selection

**Decided:** 2026-09-14
Change the CV representation and content ordering first, re-run the screening benchmark on `gpt-5.6-luna` to establish a true post-packaging baseline, and only then evaluate cheaper candidate models against that baseline.

**Rejected:** *Models first* — wire a provider and benchmark candidates on the current PDF prompt, then fix packaging afterwards. Rejected because packaging changes the token profile that every candidate's cost is computed from, so the whole bake-off would have to be re-run against the new baseline. Also rejected because it inverts the risk order: packaging is a near-zero-recall-risk change with roughly the same cost effect as a 4× cheaper model, so measuring it first means the model comparison starts from a position where a marketable headline may already exist and the recall budget can be spent deliberately rather than out of necessity.

**Consequence:** the envelope table's "implied input rate" column is provisional — it is computed on today's PDF packaging and must be recomputed once the packaging work has landed (Phase 4), before the shortlist is evaluated. Phase ordering follows: packaging and cost accounting precede any provider wiring.

## Post-implementation artifacts: ADR & Case Study

Once implementation is complete and numbers are verified, capture the architectural learnings into an Architecture Decision Record (ADR) and a case study / article draft:

1. **The Denominator Trap:** When an expensive downstream stage is optimized (e.g., fit assessment moving from Grok to Mini), an upstream screening gate can silently invert from a major cost saver to a net loss ($\rho > r$), because the dividend shrank while the gate overhead stayed fixed.
2. **The Clean-Feed Paradox:** When upstream hybrid retrieval does a better job, the downstream screener's reduction rate drops ($r \approx (1 - p_1) \times \text{TNR}_{\text{low}}$)—not because the screener regressed, but because there was less garbage to reject. Penalizing the screener for a lower reduction rate penalizes it for retrieval doing its job.
3. **The Parameterized Break-Even Model:** Modeling gate economics parameterically as a function of incoming junk ratio ($1 - p_1$), downstream cost ($p_2$), and screening cost ($x$), proving break-even resilience down to single-digit junk percentages (e.g. ~4.8% junk with `gpt-oss-120b`).

## Suggested question sequence

All 10 questions are resolved. The document is **Ready for implementation**. Execution proceeds in the phase order defined below, starting with Phase 1a.

## Implementation phases

Reordered after Q2. Phases 1a–1c are the isolated CV-text experiment; the cache work moves later because it is not a prerequisite for it.

### Phase 1a — CV text extraction

**Depends on:** nothing — Q8, Q9 and Q10 are decided
**Reviewable when:** an extraction agent turns `cv.pdf` into a layout-faithful rendering; the rendering and its SHA-256 source digest are persisted on the `user_profiles` document behind a narrow model and repository method, with `UserProfile` unchanged; the check runs once per candidate per cycle in `build_pairs` and threads the text through `PairState`; a changed PDF provably regenerates the rendering; and the manual fidelity read against `cv.pdf` has been done and recorded. No screening behaviour has changed yet.
**Touches:** a new agent module and prompt template under `agents/`, a new model in `models/users.py`, the first write path in `repository/mongo_jobs_repository.py`, `orchestration/nodes/batch.py`, `orchestration/state.py`

### Phase 1b — Screening consumes the text

**Depends on:** Phase 1a
**Reviewable when:** `ScreeningAgent.screen` accepts the CV text instead of PDF bytes, the pipeline threads it through, and the screening dataset directory carries a generated rendering beside the still-present `cv.pdf` with `entries.jsonl` and `manifest.json` untouched. Content ordering is deliberately **not** changed in this phase.
**Touches:** `agents/screening.py`, `agents/prompt_templates/screening.md`, `orchestration/nodes/pair.py`, `scripts/run_screening_benchmark.py`, `scripts/export_screening_benchmark_dataset.py`

### Phase 1c — Isolated recall measurement

**Depends on:** Phase 1b (Q7 decided: Good Recall ≥ 0.900, Fitting Recall ≥ 0.800)
**Reviewable when:** a committed report on `gpt-5.6-luna` sits beside `20260909_115647` with a stated before/after delta for input tokens per call, cost per 100, Reduction Rate, Good Recall and Fitting Recall — and the after column clears the Q7 floor. This is the review gate for whether Q2's decision survives contact with the data.
**Touches:** `benchmarks/screening/reports/`, this document

### Phase 2 — Cache-aware cost accounting

**Depends on:** nothing — Q4 is decided
**Reviewable when:** a screening run records `cache_read_tokens` in `.results.jsonl`, and both the benchmark cost line and the Grafana cost panels price cached reads separately from fresh input without double-counting.
**Touches:** `monitoring/pricing.py`, `monitoring/metrics.py`, `models/screening.py`, `agents/screening.py`, `scripts/run_screening_benchmark.py`

### Phase 3 — Content reordering

**Depends on:** Phase 1c, Phase 2
**Reviewable when:** the constant instruction-plus-CV block precedes the variable job payload in **both** agents, a re-run reports a non-zero measured cache hit rate, and recall still clears the Q7 floor. Because Phase 1c already isolated the representation change, any recall movement here is attributable to ordering alone.
**Touches:** `agents/screening.py`, `agents/prompt_templates/screening.md`, `agents/fit_assessment.py`, `agents/prompt_templates/fit_assessment.md`

### Phase 4 — Post-packaging baseline

**Depends on:** Phase 3
**Reviewable when:** a committed report on the production model states the new r, ρ and saving, and the envelope table in this plan is recomputed from it so the shortlist is evaluated against real numbers.
**Touches:** `benchmarks/screening/reports/`, this document

### Phase 5 — Provider wiring and model bake-off

**Depends on:** Phase 4 (Q7 floors: Good Recall ≥ 0.900, Fitting Recall ≥ 0.800)
**Reviewable when:** `gpt-oss-120b`, `gpt-oss-120b-turbo` and `glm-5.3-flash` each have a committed report, an unpriced model is proven to fail the run rather than report `$0.00`, and a comparison table states the chosen model with its cost and its recall plus confidence interval against the Q7 floor.
**Touches:** `agents/model_factory.py`, `monitoring/pricing.py`, `scripts/run_screening_benchmark.py`, `benchmarks/screening/reports/`

### Phase 6 — Regression floor

**Depends on:** Phase 5 (Q7 decided)
**Reviewable when:** a committed screening `baseline.json` and a smoke test fail CI if Good or Fitting Recall drops below the chosen floor, mirroring `benchmarks/retrieval/test_retrieval_smoke.py:85-103`.
**Touches:** `benchmarks/screening/dataset/<version>/baseline.json`, a new `benchmarks/screening/test_screening_smoke.py`
