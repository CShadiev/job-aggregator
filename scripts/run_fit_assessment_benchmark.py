"""Run the offline fit-assessment benchmark against a frozen dataset version."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.usage import RunUsage

from agents.fit_assessment import FitAssessmentAgent
from agents.model_factory import Model, ModelFactory
from benchmarks.fit_assessment.categories import FitCategory, category_order, score_to_category
from benchmarks.fit_assessment.metrics import (
    adjacent_accuracy,
    confusion_matrix,
    exact_accuracy,
    per_class_prf,
)
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.users import UserProfile

log = LoggerProvider.get_logger()

_DEFAULT_DATASET_ROOT = Path("benchmarks/fit_assessment/dataset")
_DEFAULT_REPORTS_DIR = Path("benchmarks/fit_assessment/reports")
_REPORT_TEMPLATE_PATH = Path(__file__).parent / "fit_assessment_benchmark_report.md"
_FAILURE_ABORT_RATIO = 0.20


@dataclass
class EntryResult:
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


def load_dataset(dataset_dir: Path) -> tuple[dict, list[dict], UserProfile, Path]:
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
            f"does not match directory name {dataset_dir.name!r}")

    entries: list[dict] = []
    with entries_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    profile = UserProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    return manifest, entries, profile, cv_path


def _parse_model(model_name: str) -> Model:
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
            assessment = await agent.assess(profile, cv_path, job)
            result.predicted_cv_score = assessment.cv_ats_match_score
            result.predicted_profile_score = assessment.profile_ats_match_score
            result.predicted_cv_category = score_to_category(assessment.cv_ats_match_score)
            result.predicted_profile_category = score_to_category(
                assessment.profile_ats_match_score)
            result.deal_breakers = list(assessment.deal_breakers)
            result.summary = assessment.summary
        except Exception as exc:  # noqa: BLE001 — per-entry isolation
            result.error = f"{type(exc).__name__}: {exc}"
            log.warning("Entry {} failed: {}", entry["id"], result.error)
    return result


async def run_benchmark(args: argparse.Namespace) -> Path:
    dataset_dir = resolve_dataset_dir(Path(args.dataset_root), args.dataset_version)
    manifest, entries, profile, cv_path = load_dataset(dataset_dir)

    if args.limit is not None:
        entries = entries[:args.limit]

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

    with capture_run_messages() as run_records:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_assess_entry(agent, semaphore, profile, cv_path, entry))
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


def _fmt_matrix(matrix: dict[str, dict[str, int]]) -> str:
    cols = list(next(iter(matrix.values())).keys()) if matrix else [
        c.value for c in category_order()]
    header = "| gold \\ pred | " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * (len(cols) + 1)) + "|"
    rows = [header, sep]
    for row_label in [c.value for c in category_order()]:
        counts = matrix.get(row_label, {})
        cells = " | ".join(str(counts.get(col, 0)) for col in cols)
        rows.append(f"| {row_label} | {cells} |")
    return "\n".join(rows)


def _fmt_prf(metrics: dict[FitCategory, dict[str, float]]) -> str:
    lines = [
        "| class | precision | recall | f1 | support |",
        "|---|---|---|---|---|", ]
    for cls in category_order():
        m = metrics[cls]
        lines.append(
            f"| {cls.value} | {m['precision']:.3f} | {m['recall']:.3f} | "
            f"{m['f1']:.3f} | {int(m['support'])} |")
    return "\n".join(lines)


def _render_report(run: BenchmarkRun) -> str:
    results = run.results
    n = len(results)
    failed = sum(1 for r in results if r.error is not None)
    completed = n - failed

    gold_profile = [r.gold_profile_category for r in results]
    pred_profile = [r.predicted_profile_category for r in results]
    gold_cv = [r.gold_cv_category for r in results]
    pred_cv = [r.predicted_cv_category for r in results]

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
        profile_exact=_fmt_pct(exact_accuracy(gold_profile, pred_profile)),
        profile_adjacent=_fmt_pct(adjacent_accuracy(gold_profile, pred_profile)),
        cv_exact=_fmt_pct(exact_accuracy(gold_cv, pred_cv)),
        cv_adjacent=_fmt_pct(adjacent_accuracy(gold_cv, pred_cv)),
        profile_confusion=_fmt_matrix(confusion_matrix(gold_profile, pred_profile)),
        profile_prf=_fmt_prf(per_class_prf(gold_profile, pred_profile)),
        cv_confusion=_fmt_matrix(confusion_matrix(gold_cv, pred_cv)),
        cv_prf=_fmt_prf(per_class_prf(gold_cv, pred_cv)),
        requests=run.usage.requests,
        input_tokens=run.usage.input_tokens,
        output_tokens=run.usage.output_tokens,
        total_tokens=run.usage.total_tokens,
        strat_axis=stratification.get("axis"),
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
                    "cv_ats_match_score": r.predicted_cv_score,
                    "profile_ats_match_score": r.predicted_profile_score,
                    "cv_category": r.predicted_cv_category.value
                    if r.predicted_cv_category else None,
                    "profile_category": (
                        r.predicted_profile_category.value
                        if r.predicted_profile_category else None),
                    "deal_breakers": r.deal_breakers or [],
                    "summary": r.summary, }
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
                    "profile_category": r.gold_profile_category.value, },
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
    args = build_parser().parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
