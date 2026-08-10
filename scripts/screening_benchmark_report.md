# Screening Benchmark Report

- Timestamp: {timestamp}
- Model: {model}
- Dataset version: {dataset_version}
- Dataset path: {dataset_path}
- Dataset: n={n_entries}, username={username}, exported_at={exported_at}
- Concurrency: {concurrency}
- Completed: {completed}/{n}  Failed: {failed}

## Headline

| Metric | Value |
|---|---|
| positive precision | {positive_precision} |
| positive recall | {positive_recall} |
| positive F1 | {positive_f1} |
| exact accuracy | {exact_accuracy} |

## Confusion matrix

{confusion_matrix}

## Per gold band (cv_category)

{band_table}

## Confidence (exploratory)

- overall: n={conf_overall_n}, mean={conf_overall_mean}, p50={conf_overall_p50}
- among correct: n={conf_correct_n}, mean={conf_correct_mean}
- among incorrect: n={conf_incorrect_n}, mean={conf_incorrect_mean}
- by gold band: {conf_by_band}

## Cost

- requests: {requests}
- input_tokens: {input_tokens}
- output_tokens: {output_tokens}
- total_tokens: {total_tokens}

## Stratification (dataset)

- axis: {strat_axis}
- positive_definition: {positive_definition}
- target_per_class: {strat_target}
- actual_per_class: {strat_actual}
