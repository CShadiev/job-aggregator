"""Pydantic models for the fit assessment agent."""

from pydantic import BaseModel, Field


class FitAssessment(BaseModel):
    """Structured fit assessment for a candidate against a job posting."""

    cv_ats_match_score: float = Field(ge=0, le=100)
    """ATS-style match score using only the CV and job description.

    Estimates the likelihood of passing automated or recruiter initial screening
    when the CV is submitted as-is.
    """

    profile_ats_match_score: float = Field(ge=0, le=100)
    """ATS-style match score using the full user profile and job description.

    Reflects the candidate's true fit against role requirements, including
    information that may not appear on the CV.
    """

    deal_breakers: list[str] = Field(default_factory=list)
    """Hard requirements from the job that the candidate does not meet.

    Examples: missing language, required technology absent from profile/CV,
    insufficient years of experience, work-authorization mismatch.
    """

    summary: str
    """Short narrative summary of the overall fit assessment."""
