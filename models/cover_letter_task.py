"""Models for manually requested cover letter generation tasks."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from models.validators import ts_validator

ts = Annotated[datetime, AfterValidator(ts_validator)]


class CoverLetterTaskStatus(StrEnum):
    """Lifecycle state of a manual cover letter generation task."""

    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class CoverLetterTask(BaseModel):
    """Tracking document for one manual generation request, keyed by (username, job_uid)."""

    username: str
    job_uid: str
    status: CoverLetterTaskStatus
    created_at: ts = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: ts = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: ts
    error: str | None = None
