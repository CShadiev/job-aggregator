"""Pydantic models for the screening agent."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ScreeningAgentOutput(BaseModel):
    """Structured LLM wire format (agent ``output_type``)."""

    worth_full_assessment: Literal[0, 1]
    """1 = keep for full assessment; 0 = drop."""

    confidence: float = Field(ge=0, le=1)
    """Confidence that ``worth_full_assessment`` is correct."""


class ScreeningResult(BaseModel):
    """Public return type from ``ScreeningAgent.screen``."""

    worth_full_assessment: bool
    confidence: float = Field(ge=0, le=1)


class ScreeningRecord(BaseModel):
    """Persisted screening document in the ``screenings`` collection."""

    username: str
    job_uid: str
    worth_full_assessment: bool
    confidence: float = Field(ge=0, le=1)
    screened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: str

    def to_result(self) -> ScreeningResult:
        return ScreeningResult(
            worth_full_assessment=self.worth_full_assessment,
            confidence=self.confidence,
        )
