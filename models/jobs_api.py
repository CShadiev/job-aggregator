"""Pydantic models and enums for the jobs HTTP API."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, field_validator

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.job_application import ApplicationStage, CoverLetterPdfKey, JobApplicationStatus
from models.validators import ts_validator

ts = Annotated[datetime, AfterValidator(ts_validator)]


class JobFeedSortField(StrEnum):
    """Sort field options for the job feed query."""

    POSTED_AT = "posted_at"
    CV_ATS_MATCH_SCORE = "cv_ats_match_score"
    PROFILE_ATS_MATCH_SCORE = "profile_ats_match_score"


class SortOrder(StrEnum):
    """Sort order direction."""

    ASC = "asc"
    DESC = "desc"


class JobFeedQuery(BaseModel):
    """Filter and sort parameters for the paginated job feed."""

    q: str | None = None
    remote: bool | None = None
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    location: str | None = None
    min_cv_ats_match_score: float | None = Field(default=None, ge=0, le=100)
    min_profile_ats_match_score: float | None = Field(default=None, ge=0, le=100)
    exclude_deal_breakers: bool = False
    application_stage: ApplicationStage | None = None
    applied: bool = False
    active_only: bool = False
    skipped: bool = False
    sort_by: JobFeedSortField = JobFeedSortField.PROFILE_ATS_MATCH_SCORE
    sort_order: SortOrder = SortOrder.DESC


class UpdateJobStatusRequest(BaseModel):
    """Partial update payload for a user's application status on a job."""

    active: bool | None = None
    applied: bool | None = None
    stage: ApplicationStage | None = None
    skipped: bool = False
    cover_letter_key: str | None = None
    cover_letter_pdf_key: CoverLetterPdfKey | None = None


class JobFeedItem(BaseModel):
    """Combined job posting, fit assessment, and user application status for feed rendering."""

    job: JobPosting
    fit: FitAssessment
    status: JobApplicationStatus | None = None


class CoverLetterGenerationStatus(StrEnum):
    """Cover letter generation state visible to API clients.

    A failed generation is retried on the next request, so clients never see it.
    """

    PENDING = "pending"
    COMPLETE = "complete"


class CoverLetterGenerationStatusResponse(BaseModel):
    """Response of the start-or-poll cover letter generation endpoint."""

    status: CoverLetterGenerationStatus


class ManualJobSubmitRequest(BaseModel):
    """Client-supplied structured job description for evaluate-this-JD."""

    job_uid: UUID
    title: str
    company: str
    description_raw: str
    url: str
    location: str = ""
    remote: bool = False
    tags: list[str] = Field(default_factory=list)
    job_types: list[str] = Field(default_factory=list)
    posted_at: ts | None = None

    @field_validator("job_uid")
    @classmethod
    def job_uid_must_be_uuid4(cls, value: UUID) -> UUID:
        """Reject non-v4 UUIDs so a client cannot overwrite a scraped ``{source}:{id}`` uid."""
        if value.version != 4:
            raise ValueError("job_uid must be a UUID4")
        return value


class ManualJobSubmitResponse(BaseModel):
    """Response of the start-or-poll manual job submission endpoint."""

    job_uid: str
    status: CoverLetterGenerationStatus
