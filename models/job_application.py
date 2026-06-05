"""Pydantic models for tracking a user's job application status."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ApplicationStage(StrEnum):
    """Pipeline stage for an individual job application."""

    APPLIED = "applied"
    HIRING_MANAGER_INTERVIEW = "hiring_manager_interview"
    TECHNICAL_INTERVIEW = "technical_interview"
    RECEIVED_OFFER = "received_offer"


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
