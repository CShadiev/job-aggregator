"""Pydantic models for tracking a user's job application status."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ApplicationStage(StrEnum):
    """Pipeline stage for an individual job application."""

    APPLIED = "applied"
    HIRING_MANAGER_INTERVIEW = "hiring_manager_interview"
    TECHNICAL_INTERVIEW = "technical_interview"
    RECEIVED_OFFER = "received_offer"


class CoverLetterPdfKey(BaseModel):
    """Key of the cover letter in the object storage."""
    source_hash: str
    value: str


class JobApplicationStatus(BaseModel):
    """Status of a user's application to a specific job posting."""

    username: str
    job_uid: str
    active: bool = Field(
        description="Whether the application is still being pursued (False when withdrawn or closed).",
        default=True,
    )
    stage: ApplicationStage = Field(
        description="The current stage of the application process.",
        default=ApplicationStage.APPLIED,
    )
    skipped: bool = Field(
        description="Whether the user has skipped this job.",
        default=False,
    )
    cover_letter_key: str | None = Field(
        description="The key of the cover letter in the object storage.",
        default=None,
    )
    cover_letter_pdf_key: CoverLetterPdfKey | None = Field(
        description="The key of the cover letter PDF in the object storage.",
        default=None,
    )
