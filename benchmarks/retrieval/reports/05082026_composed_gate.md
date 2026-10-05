# Composed Retrieval + Screening Gate — 05082026

Measured replay. No new model calls.

- Dataset: `05082026` (300 postings)
- Retrieval: hybrid at K=150 (code default `PIPELINE_RETRIEVAL_RATIO=0.5`)
- Ranked uids: `benchmarks/retrieval/reports/05082026_hybrid_ranked_uids.json`
- Screening: `gpt-5.6-luna` at t=0.0 (`benchmarks/screening/reports/20260915_125405_gpt-5.6-luna.results.jsonl`)
- Screening prompt: `/projects/job-aggregator/agents/prompt_templates/screening.md`
- Assessment cost: mean call from `benchmarks/fit_assessment/reports/20260909_173301_gpt-5.6-luna.md` (929021 input / 38263 output tokens over 100 calls, `gpt-5.6-luna` rates in `monitoring/pricing.py`)

A posting reaches fit assessment only when hybrid retrieval ranks it inside the top 150 and screening predicts `worth_full_assessment`. Good recall and fitting recall are against the full gold sets (30 good / 90 fitting), so a miss by either gate counts.

## Composed operating point

| Reduction rate | Cost reduction vs assess-all | Good recall | Fitting recall | Naive recall |
|---|---|---|---|---|
| 79.7% | 64.8% | 0.7000 | 0.5889 | 0.2033 |

## What each gate kept

| Stage | Pairs remaining | Good recall | Fitting recall |
|---|---|---|---|
| Corpus | 300 | 1.0000 | 1.0000 |
| After hybrid retrieval K=150 | 150 | 0.7667 | 0.7333 |
| After screening t=0.0 | 61 | 0.7000 | 0.5889 |

## Cost

Screening USD is the stored token cost of the retrieved calls only. Assessment USD is `n_assessed` times the mean luna fit-assessment call. The counterfactual assesses every corpus pair and pays no screening cost.

| Path | USD |
|---|---|
| Screen the top 150, assess the 61 survivors | $0.244757 |
| — screening | $0.103408 |
| — fit assessment | $0.141349 |
| Assess all 300 pairs | $0.695159 |
| Assessment cost per call | $0.002317 |

Cost reduction is `0.647912` (64.8%). This is the measured composition on this corpus. It is not the historical single-gate 23% figure and not the 61% estimate.
