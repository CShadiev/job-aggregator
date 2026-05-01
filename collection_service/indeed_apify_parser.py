"""Parser that converts raw Indeed (via Apify) dataset items into JobPostings."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from models.collection_service import IndeedRaw, JobPosting


class SearchInput(BaseModel):
    """Lightweight model representing the search parameters used in an Indeed scrape."""

    position: Optional[str] = None
    country: Optional[str] = None


class IndeedApifyParser:
    """Parse raw Indeed dataset items produced by an Apify actor into JobPostings.

    The parser relies on :class:`~models.collection_service.IndeedRaw` to validate
    and coerce the incoming dictionary before mapping fields to the canonical
    :class:`~models.collection_service.JobPosting` schema.
    """

    def __init__(self, source_tag: str):
        """Initialise the parser.

        Args:
            source_tag: Short label identifying the data source
                (e.g. ``"indeed"``), stored on every produced posting.
        """
        self.source_tag = source_tag

    def parse_job(self, raw: dict) -> JobPosting:
        """Parse a single raw Indeed dataset item into a normalised JobPosting.

        Falls back to ``scrapedAt`` when ``postingDateParsed`` is absent so that
        every returned posting always has a non-null ``posted_at`` value.

        Args:
            raw: A dictionary representing one item from an Apify Indeed dataset.

        Returns:
            A validated :class:`~models.collection_service.JobPosting` instance.
        """
        rm = IndeedRaw.model_validate(raw)
        posted_at = rm.postingDateParsed if rm.postingDateParsed is not None else rm.scrapedAt

        return JobPosting(
            uid=f"indeed:{rm.id}",
            source=self.source_tag,
            title=rm.positionName,
            company=rm.company,
            location=rm.location or "",
            remote=False,
            url=rm.url,
            tags=["python developer"],
            description_raw=rm.description,
            job_types=rm.jobType,
            posted_at=posted_at,
            collected_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
