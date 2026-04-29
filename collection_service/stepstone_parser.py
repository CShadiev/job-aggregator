"""Parser that converts raw Stepstone (via Apify) dataset items into JobPostings."""

from datetime import datetime, timezone

from models.collection_service import JobPosting


class StepstoneParser:
    """Parse raw Stepstone dataset items produced by an Apify actor into JobPostings.

    Fields are mapped directly from the Apify response structure to the canonical
    :class:`~models.collection_service.JobPosting` schema with light normalisation
    (tag and job-type strings are lower-cased).
    """

    def __init__(self, source_tag: str):
        """Initialise the parser.

        Args:
            source_tag: Short label identifying the data source
                (e.g. ``"stepstone"``), stored on every produced posting.
        """
        self.source_tag = source_tag

    def parse_job(self, raw: dict) -> JobPosting:
        """Parse a single raw Stepstone dataset item into a normalised JobPosting.

        Args:
            raw: A dictionary representing one item from an Apify Stepstone dataset.

        Returns:
            A validated :class:`~models.collection_service.JobPosting` instance.

        Note:
            The ``uid`` is currently derived from the raw Stepstone ``id`` field.
            A content-hash approach (title + company + date) is planned as a
            replacement to avoid leaking source-internal identifiers.
        """
        uid = f"stepstone:{raw['id']}"  # TODO: change this to derive from title and company
        return JobPosting.model_validate({
            "uid": uid,
            "source": self.source_tag,
            "title": raw["title"],
            "company": raw["company"],
            "location": raw.get("location", None),
            "remote": raw.get("remote", False),
            "url": raw["url"],
            "tags": [t.lower() for t in raw.get("tags", ["python developer"])],
            "description_raw": raw["description_html"] or "",
            "job_types": [t.lower() for t in raw.get("job_types", [])],
            "posted_at": raw["date_posted"],
            "collected_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
        })
