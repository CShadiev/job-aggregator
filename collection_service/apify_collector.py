"""Collector that fetches job postings from the last successful Apify actor-task run."""

from datetime import datetime
from hashlib import sha256

from aiohttp import ClientSession
from pydantic import ValidationError

from collection_service.apify_parser_protocol import IApifyParser
from config import ConfigProvider
from models.collection_service import JobPosting


def create_id(source_tag: str, title: str, company: str, date: datetime) -> str:
    """Return a deterministic, source-namespaced job ID derived from key fields.

    The ID is a SHA-256 hex digest of ``<title>_<company>_<YYYY-MM-DD>`` prefixed
    with *source_tag*, making collisions across postings virtually impossible while
    keeping the result stable across repeated collections of the same listing.
    """
    id_seed = f"{title}_{company}_{date.strftime('%Y-%m-%d')}"
    return f"{source_tag}:{sha256(id_seed.encode()).hexdigest()}"


class ApifyCollector:
    """Collect job postings from the most recent successful run of an Apify actor task.

    The collector hits the Apify REST API, downloads the run's dataset, delegates
    per-item parsing to an :class:`IApifyParser` implementation, and optionally
    filters results by a minimum posting date.
    """

    def __init__(
            self, client_session: ClientSession, task_id: str, source_tag: str,
            apify_parser: IApifyParser):
        """Initialise the collector.

        Args:
            client_session: Shared :class:`aiohttp.ClientSession` used for HTTP calls.
            task_id: Apify actor-task identifier whose dataset will be fetched.
            source_tag: Short label for the job source (e.g. ``"stepstone"``).
            apify_parser: Parser responsible for converting raw dataset items into
                :class:`~models.collection_service.JobPosting` objects.
        """
        config = ConfigProvider.get_config()
        self.apify_parser = apify_parser
        self.api_key = config.APIFY_API_KEY
        self.base_url = config.APIFY_BASE_URL
        self.client_session = client_session
        self.task_id = task_id
        self.source_tag = source_tag

    async def collect(self, min_date: datetime | None = None) -> list[JobPosting]:
        """Fetch and parse job postings from the last succeeded actor-task run.

        Args:
            min_date: When provided, only postings with ``posted_at > min_date``
                are included in the result.

        Returns:
            List of validated :class:`~models.collection_service.JobPosting` objects.

        Raises:
            ValueError: If the Apify API returns a non-200 status code.
        """
        response = await self.client_session.get(
            f"{self.base_url}/actor-tasks/{self.task_id}/runs/last/dataset/items",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            params={"status": "SUCCEEDED", "format": "json"},
        )

        if response.status != 200:
            raise ValueError(f"Failed to collect jobs: {response.status} {await response.text()}")

        data = await response.json()
        invalid_entries = 0
        validated_entries: list[JobPosting] = []
        for entry in data:
            try:
                validated_entries.append(self.apify_parser.parse_job(entry))
            except ValidationError:
                invalid_entries += 1

        if min_date:
            validated_entries = [job for job in validated_entries if job.posted_at > min_date]
        return validated_entries
