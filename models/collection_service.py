"""Pydantic models shared across the collection service layer.

All timestamp fields are normalised to UTC via :func:`~models.validators.ts_validator`
so that comparisons and storage are always timezone-aware and consistent.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, Field

from models.validators import ts_validator

ts = Annotated[datetime, AfterValidator(ts_validator)]


class JobPosting(BaseModel):
    """Canonical representation of a collected job posting.

    This model is the common output type of every collector and parser in the
    collection service.  All timestamps are coerced to UTC.
    """

    uid: str
    """Globally unique identifier for the posting, e.g. ``"stepstone:abc123"``."""

    source: str
    """Short label for the origin data source, e.g. ``"arbeitnow"``."""

    title: str
    """Job title as published by the source."""

    company: str
    """Hiring company name as published by the source."""

    location: str
    """Location string as published by the source (may be empty)."""

    remote: bool
    """Whether the position is advertised as remote-friendly."""

    url: str
    """Canonical URL of the original job posting."""

    tags: list[str] = Field(default_factory=list)
    """Normalised (lower-cased) skill/technology tags attached to the posting."""

    description_raw: str
    """Full job description, typically in HTML or plain text."""

    job_types: list[str] = Field(default_factory=list)
    """Normalised (lower-cased) employment types, e.g. ``["full-time"]``."""

    posted_at: ts
    """Timestamp when the job was published by the source, normalised to UTC."""

    collected_at: ts
    """Timestamp when the job was fetched by the collector, normalised to UTC."""

    updated_at: ts = Field(default_factory=lambda: datetime.now(timezone.utc))
    """Timestamp of the last update to this record, normalised to UTC."""

    company_normalized: Optional[str] = None
    """Canonical company name after entity resolution (populated downstream)."""

    title_normalized: Optional[str] = None
    """Canonical job title after normalisation (populated downstream)."""


class SearchInput(BaseModel):
    """Optional search parameters that may accompany a raw scraped item."""

    position: Optional[str] = None
    """Job position or keyword used in the originating search query."""

    country: Optional[str] = None
    """Country code or name used in the originating search query."""


class IndeedRaw(BaseModel):
    """Raw schema for a single item returned by the Apify Indeed scraper.

    Field names intentionally mirror the Apify dataset schema (camelCase) so
    that ``model_validate`` works without a custom alias generator.
    """

    id: str
    positionName: str
    company: str
    location: Optional[str] = None
    url: str
    description: str
    jobType: list[str] = Field(default_factory=list)
    postingDateParsed: Optional[datetime] = None
    scrapedAt: datetime
    searchInput: Optional[SearchInput] = None
    isExpired: Optional[bool] = None


class InvalidEntry(BaseModel):
    """Invalid entry with ValidationError."""

    entry: dict
    """Invalid entry."""

    error: str
    """Validation error message."""


class CollectionResult(BaseModel):
    """Result of a collection operation."""

    postings: list[JobPosting]
    """List of validated JobPosting objects."""

    invalid_entries: list[InvalidEntry]
    """List of invalid entries with validation error messages."""
