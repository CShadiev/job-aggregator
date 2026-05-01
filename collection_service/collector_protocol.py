"""Structural subtyping protocol shared by all job-posting collectors."""

from datetime import datetime
from typing import Protocol

from models.collection_service import CollectionResult


class ICollector(Protocol):
    """Interface for a collector of job postings.

    Any class that exposes ``get_source_name`` and ``collect_jobs`` with the
    expected signatures satisfies this protocol and can be used interchangeably
    in the aggregation pipeline.
    """

    def get_source_name(self) -> str:
        """Return the unique identifier of the data source.

        Returns:
            A short, stable string label for the source (e.g. ``"arbeitnow"``).
        """
        ...

    async def collect_jobs(self, min_date: datetime | None = None) -> CollectionResult:
        """Collect job postings from the source.

        Args:
            min_date: When provided, only postings newer than this timestamp should
                be returned.

        Returns:
            CollectionResult object containing validated JobPostings and invalid entries.
            Job postings are sorted by posted_at in reverse chronological order.
        """
        ...
