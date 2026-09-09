"""Run the offline fit-assessment benchmark against a frozen dataset version."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agents.fit_assessment import FitAssessmentAgent
from agents.model_factory import Model, ModelFactory
from benchmarks.fit_assessment.categories import FitCategory, category_order, score_to_category
from benchmarks.fit_assessment.metrics import (
    adjacent_accuracy,
    confusion_matrix,
    exact_accuracy,
    per_class_prf,
    score_threshold_sweep,
)
from benchmarks.screening.metrics import cost_per_100_usd
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.users import UserProfile
from monitoring.pricing import DEFAULT_RATES, UNPRICED, PricingCache

log = LoggerProvider.get_logger()

_DEFAULT_DATASET_ROOT = Path("benchmarks/fit_assessment/dataset")
_DEFAULT_REPORTS_DIR = Path("benchmarks/fit_assessment/reports")
_REPORT_TEMPLATE_PATH = Path(__file__).parent / "fit_assessment_benchmark_report.md"
_FAILURE_ABORT_RATIO = 0.20
_PRODUCTION_CV_THRESHOLD = 80.0
_SCORE_THRESHOLDS = (50.0, 70.0, 80.0, 90.0)
_PRICING = PricingCache(ttl_seconds=float("inf"))


@dataclass
class EntryResult:
    """Individual entry assessment prediction, gold labels, and execution status."""

    id: str
    job_uid: str
    gold_cv_score: float
    gold_profile_score: float
    gold_cv_category: FitCategory
    gold_profile_category: FitCategory
    predicted_cv_score: float | None = None
    predicted_profile_score: float | None = None
    predicted_cv_category: FitCategory | None = None
    predicted_profile_category: FitCategory | None = None
    deal_breakers: list[str] | None = None
    summary: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@dataclass
class BenchmarkRun:
    """Aggregated run metadata, predictions, token usage, and execution timestamp."""

    dataset_version: str
    dataset_path: Path
    model: str
    concurrency: int
    manifest: dict
    results: list[EntryResult] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
    )


def _list_versions(dataset_root: Path) -> list[str]:
    """List all dataset version subdirectories under dataset_root."""
    if not dataset_root.is_dir():
        return []
    return sorted(p.name for p in dataset_root.iterdir() if p.is_dir())


def resolve_dataset_dir(dataset_root: Path, dataset_version: str | None) -> Path:
    """Resolve directory path for the requested or single available dataset version."""
    versions = _list_versions(dataset_root)
    if dataset_version:
        dataset_dir = dataset_root / dataset_version
        if not dataset_dir.is_dir():
            available = ", ".join(versions) if versions else "(none)"
            raise SystemExit(
                f"Dataset version {dataset_version!r} not found under {dataset_root}. "
                f"Available: {available}"
            )
        return dataset_dir

    if len(versions) == 0:
        raise SystemExit(f"No dataset versions found under {dataset_root}")
    if len(versions) > 1:
        raise SystemExit(
            "Multiple dataset versions found; pass --dataset-version explicitly. "
            f"Available: {', '.join(versions)}"
        )
    return dataset_root / versions[0]


def load_dataset(dataset_dir: Path) -> tuple[dict, list[dict], UserProfile, Path]:
    """Load manifest, entries, candidate profile, and CV path from the dataset directory."""
    manifest_path = dataset_dir / "manifest.json"
    entries_path = dataset_dir / "entries.jsonl"
    profile_path = dataset_dir / "profile.json"
    cv_path = dataset_dir / "cv.pdf"

    for path in (manifest_path, entries_path, profile_path, cv_path):
        if not path.exists():
            raise SystemExit(f"Missing required dataset file: {path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_version") != dataset_dir.name:
        raise SystemExit(
            f"manifest.dataset_version={manifest.get('dataset_version')!r} "
            f"does not match directory name {dataset_dir.name!r}"
        )

    entries: list[dict] = []
    with entries_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    profile = UserProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    return manifest, entries, profile, cv_path


def _parse_model(model_name: str) -> Model:
    """Validate and convert model name string to Model enum member."""
    try:
        return Model(model_name)
    except ValueError as exc:
        valid = ", ".join(m.value for m in Model)
        raise SystemExit(f"Unknown model {model_name!r}. Valid: {valid}") from exc


async def _assess_entry(
    agent: FitAssessmentAgent,
    semaphore: asyncio.Semaphore,
    profile: UserProfile,
    cv_path: Path,
    entry: dict,
) -> EntryResult:
    """Evaluate one dataset entry using the FitAssessmentAgent."""
    gold = entry["gold"]
    result = EntryResult(
        id=entry["id"],
        job_uid=entry["job"]["uid"],
        gold_cv_score=gold["cv_ats_match_score"],
        gold_profile_score=gold["profile_ats_match_score"],
        gold_cv_category=FitCategory(gold["cv_category"]),
        gold_profile_category=FitCategory(gold["profile_category"]),
    )
    async with semaphore:
        try:
            job = JobPosting.model_validate(entry["job"])
            assessment, input_tokens, output_tokens = await agent.assess_with_usage(
                profile, cv_path, job
            )
            result.predicted_cv_score = assessment.cv_ats_match_score
            result.predicted_profile_score = assessment.profile_ats_match_score
            result.predicted_cv_category = score_to_category(assessment.cv_ats_match_score)
            result.predicted_profile_category = score_to_category(
                assessment.profile_ats_match_score
            )
            result.deal_breakers = list(assessment.deal_breakers)
            result.summary = assessment.summary
            result.input_tokens = input_tokens
            result.output_tokens = output_tokens
        except Exception as exc:  # noqa: BLE001 — per-entry isolation
            result.error = f"{type(exc).__name__}: {exc}"
            log.warning("Entry {} failed: {}", entry["id"], result.error)
    return result


async def run_benchmark(args: argparse.Namespace) -> Path:
    """Execute the offline fit-assessment evaluation run, generate markdown report and JSONL logs."""
    dataset_dir = resolve_dataset_dir(Path(args.dataset_root), args.dataset_version)
    manifest, entries, profile, cv_path = load_dataset(dataset_dir)

    if args.limit is not None:
        entries = entries[: args.limit]

    model = _parse_model(args.model)
    agent = FitAssessmentAgent(ModelFactory.get_model(model))
    semaphore = asyncio.Semaphore(args.concurrency)

    run = BenchmarkRun(
        dataset_version=manifest["dataset_version"],
        dataset_path=dataset_dir,
        model=model.value,
        concurrency=args.concurrency,
        manifest=manifest,
    )

    log.info(
        "Running fit-assessment benchmark dataset_version={} model={} n={} concurrency={}",
        run.dataset_version,
        run.model,
        len(entries),
        args.concurrency,
    )

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(_assess_entry(agent, semaphore, profile, cv_path, entry))
            for entry in entries
        ]
    run.results = [task.result() for task in tasks]

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
            f"Partial results: {reports_dir / f'{stem}.results.jsonl'}"
        )

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
    """Format float as percentage string."""
    return f"{value:.1%}"


def _fmt_recall(value: float) -> str:
    """Format recall-style metrics to 4 decimal places."""
    return f"{value:.4f}"


def _fmt_usd(value: float) -> str:
    """Format a USD amount to 4 decimal places."""
    return f"${value:.4f}"


def _estimate_run_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    """Return (usd, priced) using static DEFAULT_RATES; unknown models cost $0."""
    priced = model in DEFAULT_RATES
    rate = DEFAULT_RATES.get(model, UNPRICED)
    return _PRICING.estimate_cost_usd(rate, input_tokens, output_tokens), priced


def _fmt_headline_row(row: dict[str, float], cost: float) -> str:
    """Render the production (t=80) cover-letter gating metrics as a markdown table row."""
    return (
        f"| {_fmt_usd(cost)} | {_fmt_pct(row['reduction_rate'])} | "
        f"{int(row['llm_calls_saved'])} | {_fmt_recall(row['naive_recall'])} | "
        f"{_fmt_recall(row['good_recall'])} | {_fmt_recall(row['fitting_recall'])} |"
    )


def _fmt_sweep_table(rows: list[dict[str, float]]) -> str:
    """Render the CV-score threshold sweep as a markdown table."""
    lines = [
        "| Threshold | n passed | Reduction Rate | LLM Calls Saved | Naive Recall | Good Recall | Moderate Recall | Fitting Recall |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['threshold']:.0f} | {int(row['n_passed'])} | "
            f"{_fmt_pct(row['reduction_rate'])} | {int(row['llm_calls_saved'])} | "
            f"{_fmt_recall(row['naive_recall'])} | {_fmt_recall(row['good_recall'])} | "
            f"{_fmt_recall(row['moderate_recall'])} | {_fmt_recall(row['fitting_recall'])} |"
        )
    return "\n".join(lines)


def _fmt_matrix(matrix: dict[str, dict[str, int]]) -> str:
    """Render a confusion matrix dict as a markdown table."""
    cols = (
        list(next(iter(matrix.values())).keys()) if matrix else [c.value for c in category_order()]
    )
    header = "| gold \\ pred | " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * (len(cols) + 1)) + "|"
    rows = [header, sep]
    for row_label in [c.value for c in category_order()]:
        counts = matrix.get(row_label, {})
        cells = " | ".join(str(counts.get(col, 0)) for col in cols)
        rows.append(f"| {row_label} | {cells} |")
    return "\n".join(rows)


def _fmt_prf(metrics: dict[FitCategory, dict[str, float]]) -> str:
    """Format per-class precision, recall, and F1 as a markdown table."""
    lines = [
        "| class | precision | recall | f1 | support |",
        "|---|---|---|---|---|",
    ]
    for cls in category_order():
        m = metrics[cls]
        lines.append(
            f"| {cls.value} | {m['precision']:.3f} | {m['recall']:.3f} | "
            f"{m['f1']:.3f} | {int(m['support'])} |"
        )
    return "\n".join(lines)


def _render_report(run: BenchmarkRun) -> str:
    """Render markdown benchmark report from run results and template."""
    results = run.results
    n = len(results)
    failed = sum(1 for r in results if r.error is not None)
    completed = n - failed

    gold_profile = [r.gold_profile_category for r in results]
    pred_profile = [r.predicted_profile_category for r in results]
    gold_cv = [r.gold_cv_category for r in results]
    pred_cv = [r.predicted_cv_category for r in results]
    pred_cv_scores = [r.predicted_cv_score for r in results]

    n_good = sum(1 for c in gold_cv if c == FitCategory.GOOD)
    n_moderate = sum(1 for c in gold_cv if c == FitCategory.MODERATE)
    n_low = sum(1 for c in gold_cv if c == FitCategory.LOW)
    n_fitting = n_good + n_moderate

    sweep = score_threshold_sweep(gold_cv, pred_cv_scores, _SCORE_THRESHOLDS)
    headline = next(
        (row for row in sweep if row["threshold"] == _PRODUCTION_CV_THRESHOLD),
        sweep[0]
        if sweep
        else {
            "reduction_rate": 0.0,
            "llm_calls_saved": 0.0,
            "naive_recall": 0.0,
            "good_recall": 0.0,
            "fitting_recall": 0.0,
        },
    )

    input_tokens = sum(r.input_tokens for r in results)
    output_tokens = sum(r.output_tokens for r in results)
    total_tokens = input_tokens + output_tokens
    total_usd, priced = _estimate_run_cost(run.model, input_tokens, output_tokens)
    cost100 = cost_per_100_usd(total_usd, completed)
    cost_note = (
        "" if priced else "Unpriced model; cost shown as $0.00 (not in static DEFAULT_RATES)."
    )

    stratification = run.manifest.get("stratification", {})
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
        n_good=n_good,
        n_moderate=n_moderate,
        n_low=n_low,
        n_fitting=n_fitting,
        production_threshold=f"{_PRODUCTION_CV_THRESHOLD:.0f}",
        headline_table=_fmt_headline_row(headline, cost100),
        sweep_table=_fmt_sweep_table(sweep),
        cost_note=cost_note,
        profile_exact=_fmt_pct(exact_accuracy(gold_profile, pred_profile)),
        profile_adjacent=_fmt_pct(adjacent_accuracy(gold_profile, pred_profile)),
        cv_exact=_fmt_pct(exact_accuracy(gold_cv, pred_cv)),
        cv_adjacent=_fmt_pct(adjacent_accuracy(gold_cv, pred_cv)),
        profile_confusion=_fmt_matrix(confusion_matrix(gold_profile, pred_profile)),
        profile_prf=_fmt_prf(per_class_prf(gold_profile, pred_profile)),
        cv_confusion=_fmt_matrix(confusion_matrix(gold_cv, pred_cv)),
        cv_prf=_fmt_prf(per_class_prf(gold_cv, pred_cv)),
        requests=completed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        total_usd=_fmt_usd(total_usd),
        strat_axis=stratification.get("axis"),
        strat_target=json.dumps(stratification.get("target_per_class", {}), sort_keys=True),
        strat_actual=json.dumps(stratification.get("actual_per_class", {}), sort_keys=True),
    )


def _write_results_jsonl(path: Path, run: BenchmarkRun) -> None:
    """Save raw run predictions and gold labels to JSONL file."""
    with path.open("w", encoding="utf-8") as fh:
        meta = {
            "type": "meta",
            "dataset_version": run.dataset_version,
            "model": run.model,
            "timestamp": run.timestamp,
        }
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for r in run.results:
            if r.error is None:
                predicted = {
                    "cv_ats_match_score": r.predicted_cv_score,
                    "profile_ats_match_score": r.predicted_profile_score,
                    "cv_category": r.predicted_cv_category.value
                    if r.predicted_cv_category
                    else None,
                    "profile_category": (
                        r.predicted_profile_category.value if r.predicted_profile_category else None
                    ),
                    "deal_breakers": r.deal_breakers or [],
                    "summary": r.summary,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                }
            else:
                predicted = None
            record = {
                "type": "result",
                "id": r.id,
                "job_uid": r.job_uid,
                "gold": {
                    "cv_ats_match_score": r.gold_cv_score,
                    "profile_ats_match_score": r.gold_profile_score,
                    "cv_category": r.gold_cv_category.value,
                    "profile_category": r.gold_profile_category.value,
                },
                "predicted": predicted,
                "error": r.error,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for the fit assessment benchmark runner."""
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
        default=Model.GROK_4_3.value,
        help=f"Model name (default: {Model.GROK_4_3.value})",
    )
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent assessments")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional: evaluate only the first N entries (smoke runs)",
    )
    return parser


def main() -> None:
    """CLI entrypoint for running the fit assessment benchmark."""
    args = build_parser().parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
