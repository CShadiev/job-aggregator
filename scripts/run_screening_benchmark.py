"""Run the offline screening benchmark against a frozen dataset version."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.usage import RunUsage

from agents.model_factory import Model, ModelFactory
from agents.screening import ScreeningAgent
from benchmarks.fit_assessment.categories import FitCategory, category_order
from benchmarks.screening.metrics import (
    band_binary_accuracy,
    binary_accuracy,
    binary_confusion_matrix,
    binary_precision_recall_f1,
    confidence_summary,
)
from logger_provider import LoggerProvider
from models.collection_service import JobPosting

log = LoggerProvider.get_logger()

_DEFAULT_DATASET_ROOT = Path("benchmarks/screening/dataset")
_DEFAULT_REPORTS_DIR = Path("benchmarks/screening/reports")
_REPORT_TEMPLATE_PATH = Path(__file__).parent / "screening_benchmark_report.md"
_FAILURE_ABORT_RATIO = 0.20


@dataclass
class EntryResult:
    id: str
    job_uid: str
    gold_cv_score: float
    gold_cv_category: FitCategory
    gold_worth: bool
    predicted_worth: bool | None = None
    predicted_confidence: float | None = None
    error: str | None = None


@dataclass
class BenchmarkRun:
    dataset_version: str
    dataset_path: Path
    model: str
    concurrency: int
    manifest: dict
    results: list[EntryResult] = field(default_factory=list)
    usage: RunUsage = field(default_factory=RunUsage)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), )


def _list_versions(dataset_root: Path) -> list[str]:
    if not dataset_root.is_dir():
        return []
    return sorted(p.name for p in dataset_root.iterdir() if p.is_dir())


def resolve_dataset_dir(dataset_root: Path, dataset_version: str | None) -> Path:
    versions = _list_versions(dataset_root)
    if dataset_version:
        dataset_dir = dataset_root / dataset_version
        if not dataset_dir.is_dir():
            available = ", ".join(versions) if versions else "(none)"
            raise SystemExit(
                f"Dataset version {dataset_version!r} not found under {dataset_root}. "
                f"Available: {available}")
        return dataset_dir

    if len(versions) == 0:
        raise SystemExit(f"No dataset versions found under {dataset_root}")
    if len(versions) > 1:
        raise SystemExit(
            "Multiple dataset versions found; pass --dataset-version explicitly. "
            f"Available: {', '.join(versions)}")
    return dataset_root / versions[0]


def load_dataset(dataset_dir: Path) -> tuple[dict, list[dict], Path]:
    manifest_path = dataset_dir / "manifest.json"
    entries_path = dataset_dir / "entries.jsonl"
    cv_path = dataset_dir / "cv.pdf"

    for path in (manifest_path, entries_path, cv_path):
        if not path.exists():
            raise SystemExit(f"Missing required dataset file: {path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_version") != dataset_dir.name:
        raise SystemExit(
            f"manifest.dataset_version={manifest.get('dataset_version')!r} "
            f"does not match directory name {dataset_dir.name!r}")

    entries: list[dict] = []
    with entries_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    return manifest, entries, cv_path


def _parse_model(model_name: str) -> Model:
    try:
        return Model(model_name)
    except ValueError as exc:
        valid = ", ".join(m.value for m in Model)
        raise SystemExit(f"Unknown model {model_name!r}. Valid: {valid}") from exc


async def _screen_entry(
    agent: ScreeningAgent,
    semaphore: asyncio.Semaphore,
    cv_path: Path,
    entry: dict,
) -> EntryResult:
    gold = entry["gold"]
    result = EntryResult(
        id=entry["id"],
        job_uid=entry["job"]["uid"],
        gold_cv_score=gold["cv_ats_match_score"],
        gold_cv_category=FitCategory(gold["cv_category"]),
        gold_worth=bool(gold["worth_full_assessment"]),
    )
    async with semaphore:
        try:
            job = JobPosting.model_validate(entry["job"])
            screening = await agent.screen(cv_path, job)
            result.predicted_worth = screening.worth_full_assessment
            result.predicted_confidence = screening.confidence
        except Exception as exc:  # noqa: BLE001 — per-entry isolation
            result.error = f"{type(exc).__name__}: {exc}"
            log.warning("Entry {} failed: {}", entry["id"], result.error)
    return result


async def run_benchmark(args: argparse.Namespace) -> Path:
    dataset_dir = resolve_dataset_dir(Path(args.dataset_root), args.dataset_version)
    manifest, entries, cv_path = load_dataset(dataset_dir)

    if args.limit is not None:
        entries = entries[:args.limit]

    model = _parse_model(args.model)
    agent = ScreeningAgent(ModelFactory.get_model(model))
    semaphore = asyncio.Semaphore(args.concurrency)

    run = BenchmarkRun(
        dataset_version=manifest["dataset_version"],
        dataset_path=dataset_dir,
        model=model.value,
        concurrency=args.concurrency,
        manifest=manifest,
    )

    log.info(
        "Running screening benchmark dataset_version={} model={} n={} concurrency={}",
        run.dataset_version,
        run.model,
        len(entries),
        args.concurrency,
    )

    with capture_run_messages() as run_records:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_screen_entry(agent, semaphore, cv_path, entry))
                for entry in entries]
        run.results = [task.result() for task in tasks]

    for record in run_records:
        if isinstance(record, ModelResponse):
            run.usage = run.usage + record.usage

    n = len(run.results)
    failed = sum(1 for r in run.results if r.error is not None)
    if n and failed / n > _FAILURE_ABORT_RATIO:
        reports_dir = Path(args.reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{run.timestamp}_{run.model}"
        _write_results_jsonl(reports_dir / f"{stem}.results.jsonl", run)
        raise SystemExit(
            f"Aborting: {failed}/{n} entries failed "
            f"(>{_FAILURE_ABORT_RATIO:.0%} threshold). "
            f"Partial results: {reports_dir / f'{stem}.results.jsonl'}")

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{run.timestamp}_{run.model}"
    report_path = reports_dir / f"{stem}.md"
    results_path = reports_dir / f"{stem}.results.jsonl"

    report_path.write_text(_render_report(run), encoding="utf-8")
    _write_results_jsonl(results_path, run)

    log.info("Wrote report {} and results {}", report_path, results_path)
    print(report_path)
    return report_path


def _fmt_pct(value: float) -> str:
    return f"{value:.1%}"


def _fmt_float(value: float) -> str:
    return f"{value:.3f}"


def _fmt_matrix(matrix: dict[str, dict[str, int]]) -> str:
    cols = list(next(iter(matrix.values())).keys()) if matrix else ["true", "false"]
    header = "| gold \\ pred | " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * (len(cols) + 1)) + "|"
    rows = [header, sep]
    for row_label in ("true", "false"):
        counts = matrix.get(row_label, {})
        cells = " | ".join(str(counts.get(col, 0)) for col in cols)
        rows.append(f"| {row_label} | {cells} |")
    return "\n".join(rows)


def _fmt_band_table(bands: dict[str, dict[str, float]]) -> str:
    lines = [
        "| band | n | binary gold | correct | accuracy |",
        "|---|---|---|---|---|", ]
    for cls in category_order():
        m = bands[cls.value]
        gold_label = "true" if m["binary_gold"] else "false"
        lines.append(
            f"| {cls.value} | {int(m['n'])} | {gold_label} | "
            f"{int(m['correct'])} | {_fmt_pct(m['accuracy'])} |")
    return "\n".join(lines)


def _render_report(run: BenchmarkRun) -> str:
    results = run.results
    n = len(results)
    failed = sum(1 for r in results if r.error is not None)
    completed = n - failed

    gold_worth = [r.gold_worth for r in results]
    pred_worth = [r.predicted_worth for r in results]
    gold_categories = [r.gold_cv_category for r in results]
    confidences = [r.predicted_confidence for r in results]
    correct: list[bool | None] = [
        None if r.error is not None else (r.predicted_worth == r.gold_worth)
        for r in results]

    prf = binary_precision_recall_f1(gold_worth, pred_worth)
    bands = band_binary_accuracy(gold_categories, gold_worth, pred_worth)
    conf = confidence_summary(confidences, correct, gold_categories)
    stratification = run.manifest.get("stratification", {})

    conf_by_band = {
        band: {"n": int(stats["n"]), "mean": round(stats["mean"], 3)}
        for band, stats in conf["by_band"].items()}

    template = _REPORT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        timestamp=run.timestamp,
        model=run.model,
        dataset_version=run.dataset_version,
        dataset_path=run.dataset_path.as_posix(),
        n_entries=run.manifest.get("n_entries"),
        username=run.manifest.get("username"),
        exported_at=run.manifest.get("exported_at"),
        concurrency=run.concurrency,
        completed=completed,
        n=n,
        failed=failed,
        positive_precision=_fmt_float(prf["precision"]),
        positive_recall=_fmt_float(prf["recall"]),
        positive_f1=_fmt_float(prf["f1"]),
        exact_accuracy=_fmt_pct(binary_accuracy(gold_worth, pred_worth)),
        confusion_matrix=_fmt_matrix(binary_confusion_matrix(gold_worth, pred_worth)),
        band_table=_fmt_band_table(bands),
        conf_overall_n=int(conf["overall"]["n"]),
        conf_overall_mean=_fmt_float(conf["overall"]["mean"]),
        conf_overall_p50=_fmt_float(conf["overall"]["p50"]),
        conf_correct_n=int(conf["correct"]["n"]),
        conf_correct_mean=_fmt_float(conf["correct"]["mean"]),
        conf_incorrect_n=int(conf["incorrect"]["n"]),
        conf_incorrect_mean=_fmt_float(conf["incorrect"]["mean"]),
        conf_by_band=json.dumps(conf_by_band, sort_keys=True),
        requests=run.usage.requests,
        input_tokens=run.usage.input_tokens,
        output_tokens=run.usage.output_tokens,
        total_tokens=run.usage.total_tokens,
        strat_axis=stratification.get("axis"),
        positive_definition=stratification.get("positive_definition", ""),
        strat_target=json.dumps(stratification.get("target_per_class", {}), sort_keys=True),
        strat_actual=json.dumps(stratification.get("actual_per_class", {}), sort_keys=True),
    )


def _write_results_jsonl(path: Path, run: BenchmarkRun) -> None:
    with path.open("w", encoding="utf-8") as fh:
        meta = {
            "type": "meta",
            "dataset_version": run.dataset_version,
            "model": run.model,
            "timestamp": run.timestamp, }
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for r in run.results:
            if r.error is None:
                predicted = {
                    "worth_full_assessment": r.predicted_worth,
                    "confidence": r.predicted_confidence, }
            else:
                predicted = None
            record = {
                "type": "result",
                "id": r.id,
                "job_uid": r.job_uid,
                "gold": {
                    "cv_ats_match_score": r.gold_cv_score,
                    "cv_category": r.gold_cv_category.value,
                    "worth_full_assessment": r.gold_worth, },
                "predicted": predicted,
                "error": r.error, }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=_DEFAULT_DATASET_ROOT,
        help="Root directory for versioned datasets (default: %(default)s)",
    )
    parser.add_argument(
        "--dataset-version",
        default=None,
        help="Dataset version DDMMYYYY (required if multiple versions exist)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=_DEFAULT_REPORTS_DIR,
        help="Directory for markdown/JSONL reports (default: %(default)s)",
    )
    parser.add_argument(
        "--model",
        default=Model.LUNA_5_6.value,
        help=f"Model name (default: {Model.LUNA_5_6.value})",
    )
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent screens")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional: evaluate only the first N entries (smoke runs)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
