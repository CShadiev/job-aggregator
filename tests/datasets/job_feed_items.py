"""Deterministic dataset of :class:`JobFeedItem` objects for tests/benchmarks."""

from datetime import datetime, timedelta, timezone

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.job_application import (
    ApplicationStage,
    JobApplicationStatus,
)
from models.jobs_api import JobFeedItem

_DATASET_SIZE = 1000

_SOURCES = ["arbeitnow", "stepstone", "indeed", "linkedin", "remoteok"]
_TITLES = [
    "Software Engineer",
    "Senior Backend Developer",
    "Data Scientist",
    "DevOps Engineer",
    "Machine Learning Engineer",
    "Frontend Developer",
    "Product Manager",
    "QA Engineer",
]
_COMPANIES = [
    "Acme Corp",
    "Globex GmbH",
    "Initech",
    "Umbrella AG",
    "Hooli",
    "Stark Industries",
    "Wayne Enterprises",
]
_LOCATIONS = ["Berlin", "Munich", "Remote", "Hamburg", "Vienna", "Zurich"]
_TAGS = ["python", "fastapi", "mongodb", "react", "docker", "kubernetes", "aws", "go"]
_JOB_TYPES = ["full-time", "part-time", "contract", "internship"]
_STAGES = list(ApplicationStage)
_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_job_posting(i: int) -> JobPosting:
    source = _SOURCES[i % len(_SOURCES)]
    title = _TITLES[i % len(_TITLES)]
    company = _COMPANIES[i % len(_COMPANIES)]
    tags = [_TAGS[(i + j) % len(_TAGS)] for j in range((i % 4) + 1)]
    job_types = [_JOB_TYPES[i % len(_JOB_TYPES)]]
    return JobPosting(
        uid=f"{source}:{i:04d}",
        source=source,
        title=title,
        company=company,
        location=_LOCATIONS[i % len(_LOCATIONS)],
        remote=(i % 3 == 0),
        url=f"https://example.com/jobs/{i:04d}",
        tags=tags,
        description_raw=f"Description for {title} at {company} (#{i}).",
        job_types=job_types,
        posted_at=_BASE_TIME + timedelta(hours=i),
        collected_at=_BASE_TIME + timedelta(hours=i, minutes=30),
        updated_at=_BASE_TIME + timedelta(hours=i, minutes=45),
        company_normalized=company.lower(),
        title_normalized=title.lower(),
    )


def _make_fit_assessment(i: int) -> FitAssessment:
    cv_score = (i * 7) % 101
    profile_score = (i * 13) % 101
    deal_breakers = [f"Missing requirement {i % 5}"] if i % 5 == 0 else []
    return FitAssessment(
        cv_ats_match_score=float(cv_score),
        profile_ats_match_score=float(profile_score),
        deal_breakers=deal_breakers,
        summary=f"Fit assessment summary for job #{i}.",
    )


def _make_status(i: int, uid: str, username: str) -> JobApplicationStatus:
    return JobApplicationStatus(
        username=username,
        job_uid=uid,
        active=(i % 4 != 0),
        stage=_STAGES[i % len(_STAGES)],
        skipped=(i % 7 == 0),
    )


def generate_job_feed_items(username: str = "test_user") -> list[JobFeedItem]:
    """Return a deterministic list of 1000 :class:`JobFeedItem` objects.

    The generated values vary across items but are fully reproducible across
    runs. ``username`` is propagated to every :class:`JobApplicationStatus`.
    """
    items: list[JobFeedItem] = []
    for i in range(_DATASET_SIZE):
        job = _make_job_posting(i)
        fit = _make_fit_assessment(i)
        # Leave some items without a status to exercise the optional field.
        status = _make_status(i, job.uid, username) if i % 6 != 0 else None
        items.append(JobFeedItem(job=job, fit=fit, status=status))
    return items
