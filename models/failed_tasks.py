"""Models for LangGraph pipeline node failures."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

NodeName = Literal[
    "collect",
    "normalize",
    "dedupe",
    "persist_jobs",
    "embed_jobs",
    "build_pairs",
    "screen",
    "assess",
    "cover_letter",
]


class FailedTask(BaseModel):
    """Discriminated failure envelope for orchestration node errors."""

    node: NodeName
    thread_id: str
    cycle_id: str
    task_id: str | None = None
    error: str
    failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retryable: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
