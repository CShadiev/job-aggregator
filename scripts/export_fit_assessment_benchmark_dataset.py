"""Export a versioned frozen fit-assessment benchmark dataset from Mongo + S3.

Timezone for default ``--dataset-version``: UTC calendar date as ``DDMMYYYY``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pymongo import AsyncMongoClient

from agents.fit_assessment import _JOB_FIELDS
from benchmarks.fit_assessment.categories import FitCategory, category_order, score_to_category
from config import ConfigProvider
from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.users import UserProfile
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage

log = LoggerProvider.get_logger()

_DEFAULT_DATASET_ROOT = Path("benchmarks/fit_assessment/dataset")
_JOB_EXPORT_FIELDS = (
    *_JOB_FIELDS, "collected_at", "updated_at", "company_normalized", "title_normalized")


def _utc_today_ddmmyyyy() -> str:
    return datetime.now(timezone.utc).strftime("%d%m%Y")


def _target_per_class(n: int) -> dict[FitCategory, int]:
    base, rem = divmod(n, 3)
    targets: dict[FitCategory, int] = {}
    for i, cls in enumerate(category_order()):
        targets[cls] = base + (1 if i < rem else 0)
    return targets


def _diversify_within_band(candidates: list[dict], k: int) -> list[dict]:
    """Sample *k* candidates preferring CV-category diversity (soft preference)."""
    if k >= len(candidates):
        return list(candidates)

    by_cv: dict[FitCategory, list[dict]] = defaultdict(list)
    for item in candidates:
        by_cv[item["cv_category"]].append(item)

    for bucket in by_cv.values():
        random.shuffle(bucket)

    selected: list[dict] = []
    buckets = [by_cv[c] for c in category_order() if by_cv[c]]
    while len(selected) < k and buckets:
        next_buckets: list[list[dict]] = []
        for bucket in buckets:
            if len(selected) >= k:
                break
            if bucket:
                selected.append(bucket.pop())
            if bucket:
                next_buckets.append(bucket)
        buckets = next_buckets
    return selected


def stratified_sample(candidates: list[dict],
                      n: int) -> tuple[list[dict], dict[FitCategory, int], dict[FitCategory, int]]:
    """Stratify on profile_category; fill shortfalls from other bands.

    Returns (sample, target_per_class, actual_per_class).
    """
    if n > len(candidates):
        log.warning(
            "Requested n={} but only {} joinable assessments available; exporting all",
            n,
            len(candidates),
        )
        n = len(candidates)

    targets = _target_per_class(n)
    by_profile: dict[FitCategory, list[dict]] = defaultdict(list)
    for item in candidates:
        by_profile[item["profile_category"]].append(item)

    selected: list[dict] = []
    selected_ids: set[int] = set()
    actual: dict[FitCategory, int] = {c: 0 for c in category_order()}

    # First pass: take up to target from each band.
    shortfall = 0
    for cls in category_order():
        pool = by_profile[cls]
        take = min(targets[cls], len(pool))
        if take < targets[cls]:
            log.warning(
                "Band {} has {} entries, target was {}; shortfall={}",
                cls.value,
                len(pool),
                targets[cls],
                targets[cls] - take,
            )
            shortfall += targets[cls] - take
        chosen = _diversify_within_band(pool, take)
        for item in chosen:
            selected.append(item)
            selected_ids.add(id(item))
            actual[cls] += 1

    # Fill shortfall from bands that still have unused inventory,
    # preferring currently under-filled bands relative to target.
    if shortfall > 0:
        remaining_by_cls: dict[FitCategory, list[dict]] = {
            cls: [c for c in by_profile[cls] if id(c) not in selected_ids]
            for cls in category_order()}
        while shortfall > 0:
            donors = sorted(
                (cls for cls in category_order() if remaining_by_cls[cls]),
                key=lambda c: (actual[c] - targets[c], actual[c], c.value),
            )
            if not donors:
                break
            donor = donors[0]
            item = remaining_by_cls[donor].pop()
            selected.append(item)
            selected_ids.add(id(item))
            actual[donor] += 1
            shortfall -= 1

    random.shuffle(selected)
    return selected, targets, actual


async def _resolve_username(repo: MongoJobsRepository, username: str | None) -> str:
    if username:
        return username

    usernames = sorted({
        doc["username"]
        async for doc in repo._assessments.find({}, projection={"username": 1})})
    if not usernames:
        raise SystemExit("No assessments found in MongoDB")
    if len(usernames) > 1:
        raise SystemExit(
            "Multiple usernames have assessments; pass --username explicitly. "
            f"Found: {', '.join(usernames)}")
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
                "as": "job", }, },
        {"$unwind": "$job"}, ]
    cursor = await repo._assessments.aggregate(pipeline)
    candidates: list[dict] = []
    async for doc in cursor:
        assessment = FitAssessment.model_validate(doc["assessment"])
        job = JobPosting.model_validate(doc["job"])
        candidates.append({
            "username": username,
            "job": job,
            "assessment": assessment,
            "cv_category": score_to_category(assessment.cv_ats_match_score),
            "profile_category": score_to_category(assessment.profile_ats_match_score), })
    return candidates


def _job_payload(job: JobPosting) -> dict:
    return job.model_dump(mode="json", include=set(_JOB_EXPORT_FIELDS))


def _write_dataset(
    out_dir: Path,
    dataset_version: str,
    username: str,
    sample: list[dict],
    targets: dict[FitCategory, int],
    actual: dict[FitCategory, int],
    profile: UserProfile,
    cv_bytes: bytes,
) -> None:
    if out_dir.exists():
        log.warning("Dataset directory {} already exists; overwriting", out_dir)
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    entries_path = out_dir / "entries.jsonl"
    with entries_path.open("w", encoding="utf-8") as fh:
        for index, item in enumerate(sample):
            assessment: FitAssessment = item["assessment"]
            record = {
                "id": str(index),
                "username": username,
                "job": _job_payload(item["job"]),
                "gold": {
                    "cv_ats_match_score": assessment.cv_ats_match_score,
                    "profile_ats_match_score": assessment.profile_ats_match_score,
                    "cv_category": item["cv_category"].value,
                    "profile_category": item["profile_category"].value,
                    "deal_breakers": assessment.deal_breakers,
                    "summary": assessment.summary, }, }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    profile_path = out_dir / "profile.json"
    profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

    cv_path = out_dir / "cv.pdf"
    cv_path.write_bytes(cv_bytes)

    config = ConfigProvider.get_config()
    manifest = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "n_entries": len(sample),
        "stratification": {
            "axis": "profile_category",
            "target_per_class": {c.value: targets[c]
                                 for c in category_order()},
            "actual_per_class": {c.value: actual[c]
                                 for c in category_order()}, },
        "cv_path": "cv.pdf",
        "profile_path": "profile.json",
        "source": {
            "mongodb_database": config.MONGODB_DATABASE,
            "note": "Scores are historical FitAssessmentAgent outputs, not human labels.", }, }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


async def export_dataset(args: argparse.Namespace) -> Path:
    config = ConfigProvider.get_config()
    dataset_version = args.dataset_version or _utc_today_ddmmyyyy()
    out_dir = Path(args.dataset_root) / dataset_version

    log.info(
        "Exporting fit-assessment benchmark dataset version={} (UTC date default) to {}",
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

        profiles = await repo.get_user_profiles()
        profile_matches = [p for p in profiles if p.username == username]
        if not profile_matches:
            raise SystemExit(f"No user profile found for username={username!r}")
        profile = profile_matches[0]

        object_storage = ObjectStorage()
        try:
            cv_bytes = object_storage.get_user_cv(username)
        except Exception as exc:
            raise SystemExit(
                f"Failed to fetch CV from S3 for username={username!r}: {exc}") from exc
        if not cv_bytes:
            raise SystemExit(f"Empty CV fetched from S3 for username={username!r}")

        candidates = await _load_candidates(repo, username)
        if not candidates:
            raise SystemExit(f"No joinable assessments (with jobs) for username={username!r}")

        sample, targets, actual = stratified_sample(candidates, args.n)
        _write_dataset(
            out_dir=out_dir,
            dataset_version=dataset_version,
            username=username,
            sample=sample,
            targets=targets,
            actual=actual,
            profile=profile,
            cv_bytes=cv_bytes,
        )

        log.info(
            "Wrote dataset version={} n_entries={} actual_per_class={}",
            dataset_version,
            len(sample),
            {c.value: actual[c]
             for c in category_order()},
        )
        return out_dir
    finally:
        await mongo_client.close()


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
        help="Version id as DDMMYYYY (default: today's UTC date)",
    )
    parser.add_argument(
        "--n", type=int, default=100, help="Target number of entries (default: 100)")
    parser.add_argument(
        "--username",
        default=None,
        help="Username to export; default = sole username with assessments",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.n < 1:
        raise SystemExit("--n must be >= 1")
    out_dir = asyncio.run(export_dataset(args))
    print(out_dir)


if __name__ == "__main__":
    main()
