"""Models for manually submitted job evaluation tasks."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from models.validators import ts_validator

ts = Annotated[datetime, AfterValidator(ts_validator)]


class ManualJobTaskStatus(StrEnum):
    """Lifecycle state of a manual job submission task."""

    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class ManualJobTask(BaseModel):
    """Tracking document for one submit-and-evaluate request, keyed by (username, job_uid)."""

    username: str
    job_uid: str
    status: ManualJobTaskStatus
    created_at: ts = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: ts = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: ts
    error: str | None = None
