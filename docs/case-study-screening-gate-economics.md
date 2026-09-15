# Case study: when a screening gate starts losing money

A two-stage LLM pipeline — cheap screen, expensive fit assessment — is supposed to save money. In production it did the opposite. This note records why, what we changed, and how we now talk about the numbers.

## The denominator trap

The gate's value is not "how many jobs it drops." It is whether dropping those jobs is cheaper than assessing them. Per pair:

```
ungated spend  = assessment
gated spend    = screen + (1 − r) × assessment
saving         = r − ρ
ρ              = screen $/call ÷ assessment $/call
```

Break-even is `ρ = r`. Before assessment moved onto `gpt-5-mini`, ρ was about 0.04 and the gate saved ~60%. After that move, assessment was ~11× cheaper, ρ rose to ~0.58, and a 52% drop rate in the live post-retrieval feed produced a **6.6% loss**. The screener still dropped 64% of the stratified benchmark at 0.967 Good Recall. The work it removed had simply stopped being worth removing.

The trap is easy to miss if you only watch the gate's own cost, or only watch its reduction rate. The quantity that moved was the *denominator*.

## The clean-feed paradox

The stratified screening dataset is 30 good / 60 moderate / 210 low. Production does not look like that. Pairs are the retrieval top-K of the current batch, so the incoming mix is already cleaner. Reduction rate then falls:

```
r ≈ (1 − p₁) × TNR_low
```

where `p₁` is the fitting share of the feed. Penalizing the screener for a lower `r` after retrieval improved is penalizing it for the upstream stage doing its job. The intrinsic properties to freeze are Good Recall, Fitting Recall, and low-tier TNR — plus screening cost per call `x`. Downstream assessment cost `p₂` and feed composition are parameters, not model qualities.

Net saving across a feed is then:

```
saving ≈ (1 − p₁) × TNR_low − x / p₂
Junk_min = (x / p₂) / TNR_low
```

A model that only breaks even on a 64% junk mix is fragile. One that still breaks even at single-digit junk is the gate you want in front of a working retriever.

## Packaging before model shopping

Eighty-two percent of screening input was byte-identical across the 300-call run: the CV PDF plus instructions. That block sat *after* the job payload, so prefix caching could never see it. Two packaging changes, in that order:

1. Render the CV once as layout-faithful text, keyed to a SHA-256 of the PDF, and substitute the text for the attachment.
2. Reorder the prompt so the constant prefix and CV precede the job.

The first change is a token-count win and is visible without cache accounting. The second is a token-*price* win and is invisible unless cached reads are a first-class rate. We added `cached_input_usd_per_1m` with a conservative fallback: no published cached rate means full input price, never zero.

The CV text lives on the Mongo `user_profiles` document but **not** on the `UserProfile` model. Fit assessment and cover-letter generation dump the whole model into the prompt; a new field would have been auto-injected, and fit assessment would have carried the CV twice.

## What the eval loop is for

Candidate screeners are admitted only if they hold **Good Recall ≥ 0.900** and **Fitting Recall ≥ 0.800** on the frozen 300-entry set. Cost then decides among the survivors. That is the opposite of picking the cheapest model and hoping recall holds. CI pins the floors in `benchmarks/screening/dataset/05082026/baseline.json` against a committed results file, so a later run cannot silently publish a cheaper model that missed the budget.

The README plan's above-the-fold cost claim should be the parameterized table, not a single percentage from one cycle.

On the 2026-09-15 bake-off, `glm-5.3-flash` was the only production-packaging candidate that cleared both recall floors (Good 0.900, Fitting 0.822). It screens at $0.000477/call (ρ = 22.3% against text-CV `gpt-5-mini` assessment) and still breaks even down to a 25% junk share. The cheaper OpenAI OSS models over-dropped. `gpt-5.6-luna` held recall on the isolated text-CV prompt and lost Fitting Recall once the job payload moved last — another reminder that packaging is not recall-neutral.
