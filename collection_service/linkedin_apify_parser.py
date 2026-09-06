"""Parser that converts raw LinkedIn (via Apify) dataset items into JobPostings."""

from urllib.parse import unquote

from models.collection_service import JobPosting


class LinkedinApifyParser:
    """Parse raw LinkedIn dataset items produced by an Apify actor into JobPostings."""

    def __init__(self, source_tag: str):
        """Initialise the parser.

        Args:
            source_tag: Short label identifying the data source
                (e.g. ``"linkedin"``), stored on every produced posting.
        """
        self.source_tag = source_tag

    def parse_job(self, raw: dict) -> JobPosting:
        """Parse a single raw LinkedIn dataset item into a normalised JobPosting.

        Args:
            raw: A dictionary representing one item from an Apify LinkedIn dataset.

        Returns:
            A validated :class:`~models.collection_service.JobPosting` instance.
        """
        uid_parsed = unquote(raw["uid"])
        uid = f"linkedin:{uid_parsed}"
        return JobPosting.model_validate(
            {
                **raw,
                "uid": uid,
            }
        )
