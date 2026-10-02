"""Rewrite cover-letter JSON that was saved in a Windows code page.

``Path.write_text()`` without an encoding uses the process locale. Letters
seeded from Windows can contain bytes such as ``0x92`` for a curly apostrophe.
The production API reads those objects as UTF-8 and fails.

Objects that already decode as a UTF-8 cover letter are left untouched.
Objects that decode to the same text under every candidate code page are
rewritten as UTF-8. Disagreeing decodes are skipped so a wrong code page
cannot overwrite the object.
"""

from __future__ import annotations

import argparse
import locale
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from config import ConfigProvider
from logger_provider import LoggerProvider
from models.fit_assessment import CoverLetterContent
from repository.object_storage import S3ClientProvider

log = LoggerProvider.get_logger()

_OBJECT_ROOT = "job-aggregator"
_FALLBACK_ENCODINGS = ("cp1252", "cp1251")
_UTF8_NAMES = frozenset({"utf8", "utf_8"})


@dataclass(frozen=True)
class RewritePlan:
    """What to do with one cover-letter object."""

    action: Literal["unchanged", "rewrite", "skip"]
    body: bytes | None = None
    reason: str = ""


def _encoding_key(name: str) -> str:
    return name.lower().replace("-", "")


def candidate_encodings(preferred: str) -> tuple[str, ...]:
    """Return code pages to try after UTF-8, preferring the writer's locale.

    UTF-8 is omitted: it is always attempted first, and using it as a fallback
    cannot recover a file that already failed UTF-8.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for name in (preferred, *_FALLBACK_ENCODINGS):
        key = _encoding_key(name)
        if key in _UTF8_NAMES or key in seen:
            continue
        seen.add(key)
        ordered.append(name)
    return tuple(ordered)


def plan_cover_letter_rewrite(raw: bytes, *, encodings: tuple[str, ...]) -> RewritePlan:
    """Decide whether *raw* cover-letter bytes need a UTF-8 rewrite.

    A rewrite is returned only when every successful code-page decode produces
    the same cover-letter text. Valid UTF-8 is never reinterpreted.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None:
        try:
            CoverLetterContent.model_validate_json(text)
        except ValidationError:
            return RewritePlan("skip", reason="utf-8 object is not a cover letter")
        return RewritePlan("unchanged", reason="already utf-8")

    decoded: dict[str, str] = {}
    failures: list[str] = []
    for encoding in encodings:
        try:
            candidate = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            failures.append(f"{encoding}: {exc}")
            continue
        try:
            CoverLetterContent.model_validate_json(candidate)
        except ValidationError:
            failures.append(f"{encoding}: invalid cover letter")
            continue
        decoded[encoding] = candidate

    unique = set(decoded.values())
    if len(unique) == 1:
        body = next(iter(unique)).encode("utf-8")
        via = ", ".join(decoded)
        return RewritePlan("rewrite", body=body, reason=f"decoded with {via}")
    if len(unique) > 1:
        via = ", ".join(decoded)
        return RewritePlan("skip", reason=f"ambiguous encodings: {via}")
    detail = "; ".join(failures) or "no encoding matched"
    return RewritePlan("skip", reason=detail)


def _cover_letter_prefix(username: str | None) -> str:
    if username is None:
        return f"{_OBJECT_ROOT}/"
    return f"{_OBJECT_ROOT}/{username}/cover_letters/"


def _iter_cover_letter_keys(bucket: str, prefix: str):
    client = S3ClientProvider.get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if "/cover_letters/" in key and key.endswith(".json"):
                yield key


def rewrite_cover_letters(
    *,
    username: str | None,
    encodings: tuple[str, ...],
    dry_run: bool,
) -> dict[str, int]:
    """Scan cover-letter JSON in the configured bucket and rewrite non-UTF-8 objects.

    Returns counts keyed by ``unchanged``, ``rewrite``, and ``skip``.
    """
    config = ConfigProvider.get_config()
    bucket = config.S3_BUCKET_NAME
    client = S3ClientProvider.get_s3_client()
    prefix = _cover_letter_prefix(username)
    counts = {"unchanged": 0, "rewrite": 0, "skip": 0}
    for key in _iter_cover_letter_keys(bucket, prefix):
        raw = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        plan = plan_cover_letter_rewrite(raw, encodings=encodings)
        counts[plan.action] += 1
        if plan.action == "unchanged":
            continue
        if plan.action == "skip" or plan.body is None:
            log.warning(
                "Skipped cover letter {object_key}: {reason}",
                object_key=key,
                reason=plan.reason,
            )
            continue
        if dry_run:
            log.info(
                "Would rewrite cover letter {object_key}: {reason}",
                object_key=key,
                reason=plan.reason,
            )
            continue
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=plan.body,
            ContentType="application/json; charset=utf-8",
        )
        stored = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        CoverLetterContent.model_validate_json(stored.decode("utf-8"))
        log.info("Rewrote cover letter as UTF-8: {object_key}", object_key=key)
    log.info(
        "Cover letter encoding scan finished: unchanged={unchanged} "
        "rewritten={rewritten} skipped={skipped} dry_run={dry_run} prefix={prefix}",
        unchanged=counts["unchanged"],
        rewritten=counts["rewrite"],
        skipped=counts["skip"],
        dry_run=dry_run,
        prefix=prefix,
    )
    return counts


def main() -> None:
    """Parse CLI arguments and rewrite non-UTF-8 cover-letter objects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        default=None,
        help="Limit the scan to one user. Defaults to every cover letter in the bucket.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be rewritten without uploading.",
    )
    args = parser.parse_args()
    encodings = candidate_encodings(locale.getencoding())
    if not encodings:
        raise SystemExit("No non-UTF-8 fallback encoding is available")
    rewrite_cover_letters(username=args.username, encodings=encodings, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
