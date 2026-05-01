"""Collector that fetches job postings from the last successful Apify actor-task run."""

from datetime import datetime

from aiohttp import ClientSession, ClientTimeout, ServerTimeoutError
from pydantic import ValidationError

from config import ConfigProvider
from collection_service.apify_parser_protocol import IApifyParser
from collection_service.exceptions import CollectionTimeoutError, MissingEntriesError, CollectionAPIError
from models.collection_service import CollectionResult, InvalidEntry, JobPosting


class ApifyCollector:
    """Collect job postings from the most recent successful run of an Apify actor task.

    The collector hits the Apify REST API, downloads the run's dataset, delegates
    per-item parsing to an :class:`IApifyParser` implementation, and optionally
    filters results by a minimum posting date.
    """

    def __init__(
            self, client_session: ClientSession, task_id: str, source_tag: str, apify_parser: IApifyParser,
            run_apify_task: bool = True, api_timeout_seconds: int = 5 * 60):
        """Initialise the collector.

        Args:
            client_session: Shared :class:`aiohttp.ClientSession` used for HTTP calls.
            task_id: Apify actor-task identifier whose dataset will be fetched.
            source_tag: Short label for the job source (e.g. ``"stepstone"``).
            apify_parser: Parser responsible for converting raw dataset items into `JobPosting` objects.
            run_apify_task: If True, run Apify actor task on collection, otherwise fetch
              dataset from last succeeded run.
        """
        config = ConfigProvider.get_config()
        self.api_timeout_seconds = api_timeout_seconds
        self.apify_parser = apify_parser
        self.api_key = config.APIFY_API_KEY
        self.base_url = config.APIFY_BASE_URL
        self.client_session = client_session
        self.task_id = task_id
        self.source_tag = source_tag
        self.run_apify_task = run_apify_task

    def get_source_name(self) -> str:
        """Return the unique identifier of the data source.

        Returns:
            A short, stable string label for the source (e.g. ``"stepstone"``).
        """
        return self.source_tag

    async def collect(self, min_date: datetime | None = None) -> CollectionResult:
        """Run Apify task, download dataset, and parse job postings.

        Args:
            min_date: When provided, only postings with ``posted_at > min_date``
                are included in the result.

        Returns:
            CollectionResult object containing validated JobPostings and invalid entries.
            Job postings are sorted by posted_at in reverse chronological order.

        Raises:
            CollectionTimeoutError: If the API call exceeds ``api_timeout_seconds``.
            CollectionAPIError: If the Apify API returns a non-200 status code.
            MissingEntriesError: If the collection is incomplete (earliest entry is later than min_date).
        """

        url = ""
        try:
            if self.run_apify_task:
                url = f"{self.base_url}/actor-tasks/{self.task_id}/run-sync-get-dataset-items"
                response = await self.client_session.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json", },
                    params={"format": "json", "clean": 1},
                    timeout=ClientTimeout(total=self.api_timeout_seconds),
                )
            else:
                url = f"{self.base_url}/actor-tasks/{self.task_id}/runs/last/dataset/items"
                response = await self.client_session.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json", },
                    params={"format": "json", "clean": 1, "status": "SUCCEEDED"},
                    timeout=ClientTimeout(total=self.api_timeout_seconds),
                )
        except ServerTimeoutError as e:
            raise CollectionTimeoutError(url, self.api_timeout_seconds) from e

        if response.status not in (200, 201):
            raise CollectionAPIError(response.status, await response.text())

        data = await response.json()
        invalid_entries = []
        validated_entries: list[JobPosting] = []
        for entry in data:
            try:
                validated_entries.append(self.apify_parser.parse_job(entry))
            except ValidationError as e:
                invalid_entries.append(InvalidEntry(entry=entry, error=str(e)))

        if min_date:
            validated_entries = sorted([job for job in validated_entries if job.posted_at > min_date],
                                       key=lambda x: x.posted_at, reverse=True)
            if validated_entries:
                earliest_date = validated_entries[0].posted_at
                if earliest_date > min_date:
                    raise MissingEntriesError(earliest_date, min_date)

        return CollectionResult(postings=validated_entries, invalid_entries=invalid_entries)
