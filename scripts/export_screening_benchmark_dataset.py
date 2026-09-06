"""Export a versioned frozen screening benchmark dataset from Mongo + S3.

Timezone for default ``--dataset-version``: UTC calendar date as ``DDMMYYYY``.

v1 hardcodes stratification quotas 30 good / 60 moderate / 210 low (n=300).
Sampling uses ``random.seed(0)`` for reproducibility.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pymongo import AsyncMongoClient

from agents.fit_assessment import _JOB_FIELDS
from benchmarks.fit_assessment.categories import FitCategory, category_order, score_to_category
from benchmarks.screening.labels import category_to_worth
from config import ConfigProvider
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage

log = LoggerProvider.get_logger()

_DEFAULT_DATASET_ROOT = Path("benchmarks/screening/dataset")
_JOB_EXPORT_FIELDS = (
    *_JOB_FIELDS,
    "collected_at",
    "updated_at",
    "company_normalized",
    "title_normalized",
)
_FIXED_N = 300
_QUOTAS: dict[FitCategory, int] = {
    FitCategory.GOOD: 30,
    FitCategory.MODERATE: 60,
    FitCategory.LOW: 210,
}
_SAMPLE_SEED = 0


def _utc_today_ddmmyyyy() -> str:
    """Return current UTC date formatted as DDMMYYYY."""
    return datetime.now(UTC).strftime("%d%m%Y")


def stratified_sample(
    candidates: list[dict],
) -> tuple[list[dict], dict[FitCategory, int], dict[FitCategory, int]]:
    """Sample exactly the hardcoded quotas by ``cv_category``; abort on shortfall.

    Returns (sample, target_per_class, actual_per_class).
    """
    by_cv: dict[FitCategory, list[dict]] = defaultdict(list)
    for item in candidates:
        by_cv[item["cv_category"]].append(item)

    shortfalls: list[str] = []
    for cls, quota in _QUOTAS.items():
        available = len(by_cv[cls])
        if available < quota:
            shortfalls.append(f"{cls.value}: available={available}, required={quota}")
    if shortfalls:
        raise SystemExit(
            "Insufficient inventory for screening quotas:\n  " + "\n  ".join(shortfalls)
        )

    random.seed(_SAMPLE_SEED)
    selected: list[dict] = []
    actual: dict[FitCategory, int] = {c: 0 for c in category_order()}
    for cls in category_order():
        pool = list(by_cv[cls])
        random.shuffle(pool)
        take = _QUOTAS[cls]
        selected.extend(pool[:take])
        actual[cls] = take

    random.shuffle(selected)
    return selected, dict(_QUOTAS), actual


async def _resolve_username(repo: MongoJobsRepository, username: str | None) -> str:
    if username:
        return username

    usernames = sorted(
        {doc["username"] async for doc in repo._assessments.find({}, projection={"username": 1})}
    )
    if not usernames:
        raise SystemExit("No assessments found in MongoDB")
    if len(usernames) > 1:
        raise SystemExit(
            "Multiple usernames have assessments; pass --username explicitly. "
            f"Found: {', '.join(usernames)}"
        )
    return usernames[0]


async def _load_candidates(repo: MongoJobsRepository, username: str) -> list[dict]:
    """Join assessments to jobs for *username*; drop rows missing job docs.

    Keeps the latest assessment per job_uid (by Mongo ``_id``).
    """
    config = ConfigProvider.get_config()
    pipeline = [
        {"$match": {"username": username}},
        {"$sort": {"_id": -1}},
        {"$group": {"_id": "$job_uid", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {
            "$lookup": {
                "from": config.MONGODB_JOBS_COLLECTION,
                "localField": "job_uid",
                "foreignField": "uid",
                "as": "job",
            },
        },
        {"$unwind": "$job"},
    ]
    cursor = await repo._assessments.aggregate(pipeline)
    candidates: list[dict] = []
    async for doc in cursor:
        assessment = FitAssessment.model_validate(doc["assessment"])
        job = JobPosting.model_validate(doc["job"])
        cv_category = score_to_category(assessment.cv_ats_match_score)
        candidates.append(
            {
                "username": username,
                "job": job,
                "assessment": assessment,
                "cv_category": cv_category,
            }
        )
    return candidates


def _job_payload(job: JobPosting) -> dict:
    """Serialize JobPosting model to dict including export fields."""
    return job.model_dump(mode="json", include=set(_JOB_EXPORT_FIELDS))


def _write_dataset(
    out_dir: Path,
    dataset_version: str,
    username: str,
    sample: list[dict],
    targets: dict[FitCategory, int],
    actual: dict[FitCategory, int],
    cv_bytes: bytes,
) -> None:
    """Write entries.jsonl, cv.pdf, and manifest.json to the dataset version directory."""
    if out_dir.exists():
        log.warning("Dataset directory {} already exists; overwriting", out_dir)
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    entries_path = out_dir / "entries.jsonl"
    with entries_path.open("w", encoding="utf-8") as fh:
        for index, item in enumerate(sample):
            assessment: FitAssessment = item["assessment"]
            cv_category: FitCategory = item["cv_category"]
            record = {
                "id": str(index),
                "username": username,
                "job": _job_payload(item["job"]),
                "gold": {
                    "cv_ats_match_score": assessment.cv_ats_match_score,
                    "cv_category": cv_category.value,
                    "worth_full_assessment": category_to_worth(cv_category),
                },
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    cv_path = out_dir / "cv.pdf"
    cv_path.write_bytes(cv_bytes)

    config = ConfigProvider.get_config()
    manifest = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "exported_at": datetime.now(UTC).isoformat(),
        "username": username,
        "n_entries": len(sample),
        "stratification": {
            "axis": "cv_category",
            "target_per_class": {c.value: targets[c] for c in category_order()},
            "actual_per_class": {c.value: actual[c] for c in category_order()},
            "positive_definition": "cv_category in {moderate, good} (score >= 50)",
        },
        "cv_path": "cv.pdf",
        "source": {
            "mongodb_database": config.MONGODB_DATABASE,
            "note": (
                "CV scores are historical FitAssessmentAgent outputs, not human "
                "labels. Binary gold derived from cv_category."
            ),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


async def export_dataset(args: argparse.Namespace) -> Path:
    """Extract screening benchmark candidates, perform stratified quota sampling, and export to disk."""
    config = ConfigProvider.get_config()
    dataset_version = args.dataset_version or _utc_today_ddmmyyyy()
    out_dir = Path(args.dataset_root) / dataset_version

    log.info(
        "Exporting screening benchmark dataset version={} (UTC date default) to {}",
        dataset_version,
        out_dir,
    )

    mongo_client = AsyncMongoClient(
        host=config.MONGODB_HOST,
        port=config.MONGODB_PORT,
        username=config.MONGODB_USER,
        password=config.MONGODB_PASSWORD,
    )
    try:
        repo = MongoJobsRepository(mongo_client)
        username = await _resolve_username(repo, args.username)

        object_storage = ObjectStorage()
        try:
            cv_bytes = object_storage.get_user_cv(username)
        except Exception as exc:
            raise SystemExit(
                f"Failed to fetch CV from S3 for username={username!r}: {exc}"
            ) from exc
        if not cv_bytes:
            raise SystemExit(f"Empty CV fetched from S3 for username={username!r}")

        candidates = await _load_candidates(repo, username)
        if not candidates:
            raise SystemExit(f"No joinable assessments (with jobs) for username={username!r}")

        sample, targets, actual = stratified_sample(candidates)
        _write_dataset(
            out_dir=out_dir,
            dataset_version=dataset_version,
            username=username,
            sample=sample,
            targets=targets,
            actual=actual,
            cv_bytes=cv_bytes,
        )

        log.info(
            "Wrote dataset version={} n_entries={} actual_per_class={}",
            dataset_version,
            len(sample),
            {c.value: actual[c] for c in category_order()},
        )
        return out_dir
    finally:
        await mongo_client.close()


def build_parser() -> argparse.ArgumentParser:
    """Build and configure argument parser for the screening dataset export CLI."""
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
        help="Version id as DDMMYYYY (default: today's UTC date)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=_FIXED_N,
        help=f"Must be {_FIXED_N} (v1 fixed size); default: %(default)s",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Username to export; default = sole username with assessments",
    )
    return parser


def main() -> None:
    """CLI entrypoint for exporting a screening benchmark dataset."""
    args = build_parser().parse_args()
    if args.n != _FIXED_N:
        raise SystemExit(
            f"--n must be {_FIXED_N} for v1 (hardcoded 30/60/210 quotas); got {args.n}"
        )
    out_dir = asyncio.run(export_dataset(args))
    print(out_dir)


if __name__ == "__main__":
    main()
