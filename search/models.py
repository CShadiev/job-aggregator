"""Dataclasses and documents exchanged with OpenSearch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.job_application import JobApplicationStatus
from models.jobs_api import JobFeedItem
from search.text import strip_html

SearchMode = Literal["bm25", "knn", "hybrid"]


@dataclass
class SearchFilters:
    """Structured filters for the corpus ``jobs`` index."""

    uids: list[str] | None = None
    remote: bool | None = None
    sources: list[str] | None = None
    location: str | None = None


@dataclass
class SearchHit:
    uid: str
    score: float
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHits:
    hits: list[SearchHit]
    total: int = 0


class IndexedJob(BaseModel):
    """Document stored in the OpenSearch ``jobs`` corpus index."""

    uid: str
    title: str
    description: str
    embedding: list[float]
    source: str
    company: str
    location: str
    url: str
    job_types: list[str] = Field(default_factory=list)
    remote: bool
    posted_at: datetime

    @classmethod
    def from_posting(cls, posting: JobPosting, embedding: list[float]) -> IndexedJob:
        return cls(
            uid=posting.uid,
            title=posting.title,
            description=strip_html(posting.description_raw),
            embedding=embedding,
            source=posting.source,
            company=posting.company,
            location=posting.location,
            url=posting.url,
            job_types=list(posting.job_types),
            remote=posting.remote,
            posted_at=posting.posted_at,
        )


class DenormalizedAssessment(BaseModel):
    """Self-contained assessment document for the ``assessments`` index."""

    username: str
    job_uid: str
    cv_ats_match_score: float
    profile_ats_match_score: float
    deal_breakers: list[str] = Field(default_factory=list)
    summary: str
    status: JobApplicationStatus
    job: JobPosting

    def document_id(self) -> str:
        return assessment_document_id(self.username, self.job_uid)

    def to_opensearch_source(self) -> dict[str, Any]:
        job_dump = self.job.model_dump(mode="json")
        job_dump["description"] = strip_html(self.job.description_raw)
        source: dict[str, Any] = {
            "username": self.username,
            "job_uid": self.job_uid,
            "cv_ats_match_score": self.cv_ats_match_score,
            "profile_ats_match_score": self.profile_ats_match_score,
            "summary": self.summary,
            "status": self.status.model_dump(mode="json"),
            "job": job_dump,
        }
        if self.deal_breakers:
            source["deal_breakers"] = self.deal_breakers
        return source

    @classmethod
    def from_parts(
        cls,
        *,
        assessment: FitAssessment,
        username: str,
        job: JobPosting,
        status: JobApplicationStatus | None = None,
    ) -> DenormalizedAssessment:
        return cls(
            username=username,
            job_uid=job.uid,
            cv_ats_match_score=assessment.cv_ats_match_score,
            profile_ats_match_score=assessment.profile_ats_match_score,
            deal_breakers=list(assessment.deal_breakers),
            summary=assessment.summary,
            status=status or JobApplicationStatus(username=username, job_uid=job.uid),
            job=job,
        )

    def to_feed_item(self) -> JobFeedItem:
        return JobFeedItem(job=self.job, fit=self.to_fit_assessment(), status=self.status)

    def to_fit_assessment(self) -> FitAssessment:
        return FitAssessment(
            cv_ats_match_score=self.cv_ats_match_score,
            profile_ats_match_score=self.profile_ats_match_score,
            deal_breakers=self.deal_breakers,
            summary=self.summary,
        )

    @classmethod
    def from_opensearch_source(cls, source: dict[str, Any]) -> DenormalizedAssessment:
        job_source = dict(source.get("job") or {})
        job_source.pop("description", None)
        return cls(
            username=source["username"],
            job_uid=source["job_uid"],
            cv_ats_match_score=source["cv_ats_match_score"],
            profile_ats_match_score=source["profile_ats_match_score"],
            deal_breakers=source.get("deal_breakers") or [],
            summary=source.get("summary") or "",
            status=JobApplicationStatus.model_validate(source.get("status") or {}),
            job=JobPosting.model_validate(job_source),
        )


def assessment_document_id(username: str, job_uid: str) -> str:
    return f"{username}_{job_uid}"
