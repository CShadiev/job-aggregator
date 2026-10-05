# Evaluation loop

The three harnesses are how a prompt or a model change is judged before it becomes the default. Datasets stay on the maintainer's machine. Reports are committed.

A benchmark is a deliberate re-run. A regression floor is the frozen artifact CI can check without that dataset. Retrieval has both. Screening has a committed `baseline.json` and no CI replay. Fit assessment has neither.

## Artifact policy

Datasets are private: screening and fit-assessment exports, and the retrieval corpus (`corpus.jsonl`, `candidate.json`, `extracted_profile.json`, `manifest.json`). `baseline.json` files stay committed.

Reports are public: markdown, screening `.results.jsonl`, the hybrid ranked-uid list, and the composed-gate report.

That is why a stranger cannot reproduce a screening, fit-assessment, or retrieval *run*. They can recompute retrieval recall and the composed gate from [`05082026_hybrid_ranked_uids.json`](../benchmarks/retrieval/reports/05082026_hybrid_ranked_uids.json) plus [`20260915_125405_gpt-5.6-luna.results.jsonl`](../benchmarks/screening/reports/20260915_125405_gpt-5.6-luna.results.jsonl). The composition script does that replay with no model call:

```bash
uv run python scripts/compose_retrieval_screening_gate.py
```

## Maintainer loop

### Screening

```bash
uv run python scripts/export_screening_benchmark_dataset.py
uv run run-screening-benchmark --dataset-version 05082026
```

Export needs Mongo and S3. The run needs only the model API key and the private dataset. The report lands in `benchmarks/screening/reports/`. Change the prompt or the model, then re-run. Commit the report, not the dataset.

### Fit assessment

```bash
uv run python scripts/export_fit_assessment_benchmark_dataset.py
uv run run-fit-assessment-benchmark --dataset-version 01082026 --model gpt-5.6-luna
```

The CLI default is still `grok-4.3`. Pass `gpt-5.6-luna` when the run should match the live environment and `config.py`.

### Retrieval

Retrieval does not call a chat model. It regenerates from an existing screening dataset (same postings, same candidate, same gold labels), embeds the corpus, and ranks it in OpenSearch.

```bash
uv run generate-retrieval-benchmark-dataset --dataset-version 05082026
uv run python scripts/run_retrieval_benchmark.py --dataset-version 05082026
uv run python scripts/compose_retrieval_screening_gate.py
```

The benchmark writes a timestamped report and `benchmarks/retrieval/reports/<version>_hybrid_ranked_uids.json`. The composition step intersects that list with the pinned luna screening results.

`benchmarks/retrieval/test_retrieval_smoke.py::test_hybrid_gating_meets_baseline` re-indexes the private corpus. It skips when those files are absent. CI does not run it.

## What the benchmarks decided

The live environment still runs `gpt-5.6-luna` for screening, fit assessment, and cover letters. Fit-assessment and cover-letter defaults in `config.py` match that. Screening does not.

On the production prompt packaging (constant prefix, job payload last), luna's fitting recall was **0.7889**, under the 0.800 floor ([`20260915_125405`](../benchmarks/screening/reports/20260915_125405_gpt-5.6-luna.md)). The same packaging on `glm-5.3-flash` cleared both floors: good recall 0.9000, fitting recall 0.8222, at $0.0477 per 100 calls ([`20260915_bakeoff`](../benchmarks/screening/reports/20260915_bakeoff.md)). `SCREENING_MODEL` therefore defaults to `glm-5.3-flash`. The live environment has not switched yet. `benchmarks/screening/dataset/05082026/baseline.json` pins that glm run. It is the destination of the switch, not a description of what is deployed. An isolated luna run that kept the old job-then-CV order held fitting recall 0.8222 ([`20260915_125236`](../benchmarks/screening/reports/20260915_125236_gpt-5.6-luna.md)); packaging was not recall-neutral, which is why the model choice was made on the reordered prompt.

The published README numbers follow luna, because that is what the running instance calls.

Production screening ignores the confidence score (`route_after_screen` passes iff `worth_full_assessment`). On [`20260909_115647`](../benchmarks/screening/reports/20260909_115647_gpt-5.6-luna.md) confidence averages 0.946. The t=0.0 and t=0.5 rows are identical (108 passed). t=0.7 passes 107 and t=0.8 passes 106, so cutoffs below 0.9 move one or two pairs on that run. The production-packaging luna run is flat through t=0.5 and then drops at t=0.8 (85 passed → 73). Confidence is not the lever the pipeline uses.

The pair gate moved from a fixed top-K to a ratio of the batch in `cb364f2`. On this 300-job corpus `PIPELINE_RETRIEVAL_RATIO=0.5` is K=150. The retrieval report headlines that cutoff. K=20 remains in the sweep: hybrid good recall there is 0.1667, barely above the random baseline of 0.0667, which is why a tight top-K is not the production gate.

The composed measurement replays K=150 against the luna predictions that match the current prompt. It is the number in the README. It is a different claim from the single-gate arithmetic and from the earlier estimate that assumed screening's full-corpus drop rate would hold on the retrieved subset.

## Limits

The datasets are one candidate. Gold labels are historical production assessments, not a second human rater. Good means historical CV score ≥ 70, fitting means ≥ 50. A gate can look strong on this corpus and still be wrong about a different CV. The fit-assessment set is 100 entries stratified on profile category; its cover-letter metrics use gold CV bands, and a gold-good job scored 70–79 does not pass the production threshold of 80 even when the model reproduces the label.
