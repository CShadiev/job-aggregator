"""Pydantic models for the deduplication / normalisation agent."""

from pydantic import BaseModel

from models.collection_service import JobPosting


class NormalizedJobEntry(BaseModel):
    """A single normalized job entry returned by the AI agent."""

    id: str
    """Temporary batch-local ID used to reconcile results with original postings."""

    company: str
    """Normalized company name."""

    title: str
    """Normalized job title."""


class NormalizedBatch(BaseModel):
    """Top-level result type returned by the AI agent for a single batch."""

    jobs: list[NormalizedJobEntry]
    """Normalized entries in the same order as the input batch."""


class FailedJobPosting(BaseModel):
    """A job posting that could not be normalized, with an attached error message."""

    posting: JobPosting
    """The original job posting that failed normalization."""

    error: str
    """Human-readable description of why normalization failed for this posting."""


class NormalizationResult(BaseModel):
    """Outcome of a full normalization run across all batches."""

    processed: list[JobPosting]
    """Postings with :attr:`~models.collection_service.JobPosting.title_normalized`
    and :attr:`~models.collection_service.JobPosting.company_normalized` filled in."""

    failed: list[FailedJobPosting]
    """Postings that could not be normalized after all retries were exhausted."""
