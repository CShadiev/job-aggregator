"""Structural subtyping protocol for Apify dataset item parsers."""

from typing import Protocol

from models.collection_service import JobPosting


class IApifyParser(Protocol):
    """Interface for objects that convert a raw Apify dataset item into a JobPosting.

    Any class that implements a ``parse_job(raw: dict) -> JobPosting`` method is
    considered a structural subtype of this protocol and can be used wherever an
    ``IApifyParser`` is expected.
    """

    def parse_job(self, raw: dict) -> JobPosting:
        """Parse a single raw Apify dataset item into a normalised JobPosting.

        Args:
            raw: A dictionary representing one item from an Apify actor-task dataset.

        Returns:
            A validated :class:`~models.collection_service.JobPosting` instance.
        """
        ...
