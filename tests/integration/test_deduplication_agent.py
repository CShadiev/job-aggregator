import pytest
from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.usage import RunUsage

from agents.deduplication import DeduplicationAgent
from config import ConfigProvider
from logger_provider import LoggerProvider
from tests.datasets.deduplication_benchmark import load_benchmark_dataset
from tests.helpers.job_posting import make_job_posting

from agents.model_factory import Model, ModelFactory

log = LoggerProvider.get_logger()
config = ConfigProvider.get_config()

MODEL_NAME = Model.GROK_4_3
ACCURACY_THRESHOLD = 0.5
DEDUPLICATION_METRIC_MAX = 0.10


def get_agent() -> DeduplicationAgent:
    model = ModelFactory.get_model(MODEL_NAME)
    return DeduplicationAgent(model)


def count_deduped_by_normalized_key(processed: list, ) -> int:
    seen: set[tuple[str, str]] = set()
    for posting in processed:
        key = (posting.title_normalized, posting.company_normalized)
        seen.add(key)
    return len(seen)


@pytest.mark.priced
async def test_benchmark_normalization_accuracy():
    dataset = load_benchmark_dataset()
    assert len(dataset) == 30

    postings = [
        make_job_posting(
            uid=f"benchmark:{index}",
            title=entry["title"],
            company=entry["company"],
        ) for index, entry in enumerate(dataset)]

    log.info("Deduplication benchmark model={}", MODEL_NAME)

    agent = get_agent()
    with capture_run_messages() as run_records:
        result = await agent.normalize(postings)

    processed_by_uid = {posting.uid: posting for posting in result.processed}
    correct = 0
    mismatches: list[str] = []

    for index, entry in enumerate(dataset):
        uid = f"benchmark:{index}"
        processed = processed_by_uid.get(uid)

        if processed is None:
            failed = next(
                (item for item in result.failed if item.posting.uid == uid),
                None,
            )
            error = failed.error if failed else "missing from agent output"
            mismatches.append(
                f"[{index}] failed normalization: title={entry['title']!r} "
                f"company={entry['company']!r} error={error!r}", )
            log.info(
                "Benchmark output [{}]: status=failed title={!r} company={!r} error={!r}",
                index,
                entry["title"],
                entry["company"],
                error,
            )
            continue

        title_match = processed.title_normalized == entry["expected_normalized_title"]
        company_match = processed.company_normalized == entry["expected_normalized_company"]
        is_correct = title_match and company_match

        log.info(
            "Benchmark output [{}]: status={} input_title={!r} input_company={!r} "
            "title_normalized={!r} company_normalized={!r} "
            "expected_title={!r} expected_company={!r}",
            index,
            "match" if is_correct else "mismatch",
            entry["title"],
            entry["company"],
            processed.title_normalized,
            processed.company_normalized,
            entry["expected_normalized_title"],
            entry["expected_normalized_company"],
        )

        if is_correct:
            correct += 1
        else:
            mismatches.append(
                f"[{index}] title={entry['title']!r} company={entry['company']!r} "
                f"got title_normalized={processed.title_normalized!r} "
                f"company_normalized={processed.company_normalized!r} "
                f"expected title={entry['expected_normalized_title']!r} "
                f"company={entry['expected_normalized_company']!r}", )

    accuracy = correct / len(dataset)
    total_usage = RunUsage()
    for record in run_records:
        if isinstance(record, ModelResponse):
            total_usage = total_usage + record.usage

    log.info(
        "Benchmark run cost: model={} requests={} input_tokens={} output_tokens={} "
        "total_tokens={}",
        MODEL_NAME,
        total_usage.requests,
        total_usage.input_tokens,
        total_usage.output_tokens,
        total_usage.total_tokens,
    )

    n_total = len(dataset)
    n_target = sum(1 for entry in dataset if not entry["is_duplicate"])
    n_deduped = count_deduped_by_normalized_key(list(processed_by_uid.values()))
    deduplication_metric = (n_deduped - n_target) / n_total

    log.info(
        "Benchmark accuracy: {}/{} ({:.1%}) threshold={:.0%}",
        correct,
        len(dataset),
        accuracy,
        ACCURACY_THRESHOLD,
    )
    log.info(
        "Benchmark deduplication: n_target={} n_deduped={} n_total={} "
        "metric={:.3f} max={:.2f}",
        n_target,
        n_deduped,
        n_total,
        deduplication_metric,
        DEDUPLICATION_METRIC_MAX,
    )
    for mismatch in mismatches:
        log.warning("Benchmark mismatch: {}", mismatch)

    assert not result.failed, f"Unexpected normalization failures: {result.failed}"
    assert accuracy >= ACCURACY_THRESHOLD, (
        f"Accuracy {accuracy:.1%} below threshold {ACCURACY_THRESHOLD:.0%}. "
        f"Mismatches: {mismatches}")
    assert 0 <= deduplication_metric <= DEDUPLICATION_METRIC_MAX, (
        f"Deduplication metric {deduplication_metric:.3f} outside "
        f"allowed range [0, {DEDUPLICATION_METRIC_MAX:.2f}]. "
        f"n_target={n_target} n_deduped={n_deduped} n_total={n_total}")
