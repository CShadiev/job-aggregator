import pytest
from genai_prices import calc_price
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage

from agents.deduplication import DeduplicationAgent
from config import ConfigProvider
from logger_provider import LoggerProvider
from tests.datasets.deduplication_benchmark import load_benchmark_dataset
from tests.helpers.job_posting import make_job_posting

log = LoggerProvider.get_logger()
config = ConfigProvider.get_config()

MODEL_NAME = "gpt-4o-mini"
ACCURACY_THRESHOLD = 0.90


def get_agent() -> DeduplicationAgent:
    model = OpenAIChatModel(model_name="gpt-5-mini", provider=OpenAIProvider(api_key=config.OPENAI_API_KEY))
    return DeduplicationAgent(model)


@pytest.mark.priced
async def test_benchmark_normalization_accuracy():
    dataset = load_benchmark_dataset()
    assert len(dataset) == 20

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

    price = calc_price(total_usage, MODEL_NAME, provider_id="openai")
    log.info(
        "Benchmark run cost: model={} requests={} input_tokens={} output_tokens={} "
        "total_tokens={} input_price=${:.6f} output_price=${:.6f} total_price=${:.6f}",
        MODEL_NAME,
        total_usage.requests,
        total_usage.input_tokens,
        total_usage.output_tokens,
        total_usage.total_tokens,
        price.input_price,
        price.output_price,
        price.total_price,
    )

    log.info(
        "Benchmark accuracy: {}/{} ({:.1%}) threshold={:.0%}",
        correct,
        len(dataset),
        accuracy,
        ACCURACY_THRESHOLD,
    )
    for mismatch in mismatches:
        log.warning("Benchmark mismatch: {}", mismatch)

    assert not result.failed, f"Unexpected normalization failures: {result.failed}"
    assert accuracy >= ACCURACY_THRESHOLD, (
        f"Accuracy {accuracy:.1%} below threshold {ACCURACY_THRESHOLD:.0%}. "
        f"Mismatches: {mismatches}")
