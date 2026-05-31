"""Collector that sources job postings directly from the Arbeitnow public API."""

import asyncio
from datetime import datetime

from aiohttp import ClientSession

from config import ConfigProvider
from models.collection_service import CollectionResult, JobPosting

from logger_provider import LoggerProvider

log = LoggerProvider.get_logger()


class ArbeitnowCollector:
    """Collect job postings from the Arbeitnow public REST API.

    Paginates through the API until either *max_pages* have been fetched or a
    posting older than *min_date* is encountered.  A 429 response triggers an
    automatic 30-second back-off before retrying the same page.
    """

    def __init__(self, client: ClientSession | None = None):
        """Initialise the collector.

        Args:
            client: Optional pre-existing :class:`aiohttp.ClientSession`.  A new
                session is created automatically when this argument is omitted.
        """
        config = ConfigProvider.get_config()
        self._source = "arbeitnow"
        self.base_url = config.ARBEITNOW_BASE_URL
        self.client = client or ClientSession()

    def get_source_name(self) -> str:
        """Return the unique identifier of the data source."""
        return self._source

    async def filter_jobs(self, postings: list[JobPosting]) -> list[JobPosting]:
        """Filter job postings to only include those that are relevant to the user."""
        return [posting for posting in postings if "python" in posting.description_raw.lower()]

    async def collect_jobs(self, min_date: datetime | None = None) -> CollectionResult:
        """Collect job postings from the source (``ICollector`` entry point).

        Uses *min_date* as the pagination stop condition when provided; otherwise
        fetches up to :attr:`~config._Config.ARBEITNOW_MAX_PAGES` pages.
        """
        config = ConfigProvider.get_config()
        max_pages = None if min_date else config.ARBEITNOW_MAX_PAGES
        log.info("Collecting jobs from Arbeitnow", min_date=min_date)
        postings = await self.collect(min_date=min_date, max_pages=max_pages)
        log.info(f"Collected {len(postings)} jobs from Arbeitnow")
        postings = await self.filter_jobs(postings)
        log.info(f"{len(postings)} jobs after filtering")
        return CollectionResult(postings=postings, invalid_entries=[])

    async def collect(
        self,
        min_date: datetime | None = None,
        max_pages: int | None = None,
        skip_pages: int | None = None,
    ) -> list:
        """Collect job postings, paginating up to *max_pages*.

        At least one of *max_pages* or *min_date* must be supplied so that the
        pagination loop has a termination condition.

        Args:
            min_date: Stop collecting once a posting with ``posted_at <= min_date``
                is encountered and return the postings gathered so far.
            max_pages: Maximum number of pages to fetch before stopping.
            skip_pages: Number of leading pages to skip before collecting begins.

        Returns:
            List of validated :class:`~models.collection_service.JobPosting` objects.

        Raises:
            ValueError: If neither *max_pages* nor *min_date* is provided.
        """
        postings = []
        url = self.base_url

        if not any([max_pages, min_date]):
            raise ValueError("Either max_pages or min_date must be provided")

        page = (skip_pages or 0) + 1
        page_count = 0
        while True:
            response = await self.client.get(url, params={"page": page})

            if response.status in [429, 403]:
                await asyncio.sleep(30)
                continue

            response.raise_for_status()

            data = await response.json()
            page_items = data.get("data", [])

            for item in page_items:
                job = self._parse_job(item)
                if min_date and job.posted_at <= min_date:
                    return postings

                postings.append(job)

            page_count += 1
            if max_pages and page_count >= max_pages:
                break

            page += 1

        return postings

    def _parse_job(self, raw: dict) -> JobPosting:
        """Convert a single Arbeitnow API item into a normalised JobPosting.

        Args:
            raw: A dictionary representing one item from the Arbeitnow ``/jobs``
                endpoint response.

        Returns:
            A :class:`~models.collection_service.JobPosting` instance.
        """
        return JobPosting(
            uid=f"arbeitnow:{raw['slug']}",
            source=self._source,
            title=raw["title"],
            company=raw["company_name"],
            location=raw.get("location", ""),
            remote=raw.get("remote", False),
            url=raw["url"],
            tags=[t.lower() for t in raw.get("tags", [])],
            description_raw=raw.get("description", ""),
            job_types=[t.lower() for t in raw.get("job_types", [])],
            posted_at=datetime.fromtimestamp(raw["created_at"]),
            collected_at=datetime.now(),
        )

    async def cleanup(self):
        """Close the underlying HTTP client session."""
        await self.client.close()
