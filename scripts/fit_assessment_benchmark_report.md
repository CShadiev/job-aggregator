# Fit Assessment Benchmark Report

- Timestamp: {timestamp}
- Model: {model}
- Dataset version: {dataset_version}
- Dataset path: {dataset_path}
- Dataset: n={n_entries}, username={username}, exported_at={exported_at}
- Concurrency: {concurrency}
- Completed: {completed}/{n}  Failed: {failed}

## Headline

| Score | Exact accuracy | Adjacent accuracy |
|---|---|---|
| profile_ats_match_score | {profile_exact} | {profile_adjacent} |
| cv_ats_match_score | {cv_exact} | {cv_adjacent} |

## Profile — confusion matrix

{profile_confusion}

## Profile — per-class metrics

{profile_prf}

## CV — confusion matrix

{cv_confusion}

## CV — per-class metrics

{cv_prf}

## Cost

- requests: {requests}
- input_tokens: {input_tokens}
- output_tokens: {output_tokens}
- total_tokens: {total_tokens}

## Stratification (dataset)

- axis: {strat_axis}
- target_per_class: {strat_target}
- actual_per_class: {strat_actual}
