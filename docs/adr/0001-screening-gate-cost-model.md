# ADR 0001 — Screening-gate cost model

**Status:** Accepted  
**Date:** 2026-09-15  
**Plan:** [`docs/planning/screening-gate-cost-reduction-implementation-plan.md`](../planning/screening-gate-cost-reduction-implementation-plan.md)

## Context

The pipeline's screening gate exists to drop obvious non-fits before fit assessment. After assessment moved from `grok-4.3` to `gpt-5-mini`, live cycles showed the gate *adding* spend: screening 300 pairs cost more than assessing all 300 outright. The gate had not lost recall; the work it removed had become cheap.

The identity that makes this visible is:

```
saving ≈ r − ρ
ρ = screening $/call ÷ assessment $/call
```

The gate breaks even at `ρ = r`. A cheaper downstream stage shrinks the dividend while the gate's overhead stays fixed — the denominator trap. Independently, better upstream retrieval lowers the junk share arriving at the screener, so the observed reduction rate `r` falls even when the screener's low-tier true-negative rate is unchanged — the clean-feed paradox.

Two packaging defects made ρ worse than it needed to be:

1. Screening and fit assessment attached the CV as a PDF. Most of the input tokens were the same bytes on every call.
2. The variable job payload preceded that constant block, so prefix caching could never key on it.

## Decision

1. **Replace the PDF with a layout-faithful text rendering**, generated once per CV change by an LLM, stored on the `user_profiles` document *outside* `UserProfile`, and freshness-checked in `build_pairs` against a SHA-256 of the PDF bytes.
2. **Send constant content first** in both screening and fit assessment: instruction prefix, CV text, job payload last.
3. **Price cached input tokens** as a first-class `ModelRate` field. `input_tokens` includes cached tokens on OpenAI-compatible providers, so cost is `(input − cache_read) × input_rate + cache_read × cached_rate`. An absent cached rate falls back to the full input rate.
4. **Report gate economics parameterically**, not as a single percentage: cost ratio `ρ`, low-tier TNR, break-even junk share, and a sensitivity table over feed composition. Dual recall floors stay fixed: Good Recall ≥ 0.900 and Fitting Recall ≥ 0.800.

## Consequences

- `UserProfile` remains the prompt payload. Derived CV fields cannot leak into fit-assessment or cover-letter dumps.
- Pair state carries `cv_text`, retiring per-pair S3 downloads of the same PDF.
- Grafana cost panels move when caching works, because `record_agent_usage` now prices cache reads.
- The screening benchmark fails closed on an unpriced model instead of publishing `$0.00`.
- Headline savings depend on the incoming junk share. A lower production `r` than the stratified benchmark is evidence that retrieval is doing its job, not that screening regressed.
- Production screening runs `glm-5.3-flash` on DeepInfra. That was the only Phase 5 candidate that cleared Good Recall ≥ 0.900 and Fitting Recall ≥ 0.800 on the reordered text-CV prompt.

## Rejected alternatives

- Parser-based PDF extraction — cannot preserve multi-column CV layout.
- Dumping `UserProfile` in place of the CV — contradicts the screening prompt's "CV only" contract and the gold labels' provenance.
- Fields on `UserProfile` with `exclude=` at dump sites — fails the first time a new caller forgets.
- Treating cached reads as free — overstates a published cost claim.
- Headlining a single empirical reduction rate — hides the dependence on feed composition.
