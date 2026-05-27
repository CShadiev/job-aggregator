from datetime import datetime, timezone

from models.collection_service import JobPosting
from models.deduplication import NormalizedBatch, NormalizedJobEntry


def make_job_posting(**overrides) -> JobPosting:
    defaults = {
        "uid": "test:1",
        "source": "test",
        "title": "Software Engineer",
        "company": "Acme Corp",
        "location": "",
        "remote": False,
        "url": "https://example.com/jobs/1",
        "description_raw": "Job description",
        "posted_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "collected_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def make_normalized_batch(entries: list[tuple[str, str, str]]) -> NormalizedBatch:
    return NormalizedBatch(
        jobs=[
            NormalizedJobEntry(id=id_, title=title, company=company)
            for id_, title, company in entries
        ]
    )
