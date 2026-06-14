from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.job_application import ApplicationStage, JobApplicationStatus


class JobFeedSortField(StrEnum):
    POSTED_AT = "posted_at"
    CV_ATS_MATCH_SCORE = "cv_ats_match_score"
    PROFILE_ATS_MATCH_SCORE = "profile_ats_match_score"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class JobFeedQuery(BaseModel):
    """Filter and sort parameters for the paginated job feed."""

    remote: Optional[bool] = None
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    location: Optional[str] = None
    min_cv_ats_match_score: Optional[float] = Field(default=None, ge=0, le=100)
    min_profile_ats_match_score: Optional[float] = Field(default=None, ge=0, le=100)
    exclude_deal_breakers: bool = False
    application_stage: Optional[ApplicationStage] = None
    applied: bool = False
    active_only: bool = False
    skipped: bool = False
    sort_by: JobFeedSortField = JobFeedSortField.PROFILE_ATS_MATCH_SCORE
    sort_order: SortOrder = SortOrder.DESC


class UpdateJobStatusRequest(BaseModel):
    """Partial update payload for a user's application status on a job."""

    active: Optional[bool] = None
    stage: Optional[ApplicationStage] = None
    skipped: Optional[bool] = False


class JobFeedItem(BaseModel):
    job: JobPosting
    fit: FitAssessment
    status: JobApplicationStatus | None = None
