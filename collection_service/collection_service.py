from datetime import datetime, timedelta, timezone
from typing import Protocol

from agents.deduplication import DeduplicationAgent
from collection_service.collector_protocol import ICollector
from models.collection_service import CollectionResult, InvalidEntry, JobPosting
from models.deduplication import NormalizationResult


class IRepository(Protocol):

    async def get_checkpoint(self, source_id: str) -> datetime | None:
        """Return the high-water mark timestamp for a given source.

        The checkpoint is the ``posted_at`` value of the most recently stored
        posting for this source.  It is passed to the collector so that only
        newer postings are fetched on subsequent runs.

        Args:
            source_id: Stable string identifier of the data source
                (e.g. ``"arbeitnow"``).

        Returns:
            The stored checkpoint timestamp, or ``None`` if the source has
            never been collected before.
        """
        ...

    async def set_checkpoint(self, source_id: str, checkpoint: datetime) -> None:
        """Persist the latest checkpoint timestamp for a given source.

        Should be called by the downstream storage handler after postings have
        been successfully saved so that the next collection run can resume from
        this point in time.

        Args:
            source_id: Stable string identifier of the data source.
            checkpoint: UTC timestamp to store as the new high-water mark,
                typically the maximum ``posted_at`` value across all postings
                saved in the current run.
        """
        ...

    async def get_existing_uids(self, uids: set[str]) -> set[str]:
        """Return the subset of *uids* that already exist in the store.

        Used during deduplication to skip postings that were processed in a
        previous run, preventing duplicates caused by checkpoint overlap.

        Args:
            uids: Candidate posting UIDs to look up.

        Returns:
            The intersection of *uids* with the UIDs currently in the store.
            Returns an empty set when *uids* is empty.
        """
        ...

    async def get_recent_normalized_keys(
        self,
        keys: set[tuple[str, str]],
        since: datetime,
    ) -> set[tuple[str, str]]:
        """Return the subset of *keys* that match postings already in the store.

        A key matches when a stored posting has the same
        ``(title_normalized, company_normalized)`` pair **and** a ``posted_at``
        timestamp on or after *since*.  Used to suppress new postings that are
        effectively re-advertisements of a role seen recently.

        Args:
            keys: Candidate ``(title_normalized, company_normalized)`` pairs
                to look up.
            since: Lower-bound timestamp (UTC); only stored postings whose
                ``posted_at >= since`` are considered when matching.

        Returns:
            The subset of *keys* for which a matching recent posting exists.
            Returns an empty set when *keys* is empty.
        """
        ...


class CollectionService:
    """Orchestrates the job-posting ingestion pipeline.

    Fetches postings from multiple sources via :class:`ICollector` instances,
    normalises job titles and company names using an AI agent, and applies
    cross-source deduplication.  Persistence is intentionally left to a
    downstream handler; this service only returns the processed results.
    """

    def __init__(
        self,
        collectors: list[ICollector],
        repo: IRepository,
        agent: DeduplicationAgent,
    ):
        """
        Args:
            collectors: One collector per data source to pull postings from.
            repo: Repository used for checkpoint reads and deduplication lookups.
            agent: AI agent responsible for normalising titles and company names.
        """
        self.collectors = collectors
        self.repo = repo
        self.agent = agent

    async def collect(self) -> CollectionResult:
        """Fetch raw postings from every registered source.

        Each collector is queried with the checkpoint stored for its source so
        that only postings newer than the previous run are returned.  Results
        from all sources are merged into a single :class:`CollectionResult`.

        Returns:
            A :class:`~models.collection_service.CollectionResult` whose
            ``postings`` list contains all valid postings gathered in this run
            and ``invalid_entries`` lists any items that failed schema
            validation.

        Note:
            Checkpoints are *not* updated here; advancing them is the
            responsibility of the downstream storage handler.
        """
        # TODO: handle gaps in records (i.e. no overlap in timestamps)
        collection_result = CollectionResult(postings=[], invalid_entries=[])
        for collector in self.collectors:
            checkpoint = await self.repo.get_checkpoint(collector.get_source_name())
            _result = await collector.collect_jobs(checkpoint)
            collection_result.postings.extend(_result.postings)
            collection_result.invalid_entries.extend(_result.invalid_entries)
        return collection_result

    async def normalize(self, postings: list[JobPosting]) -> NormalizationResult:
        """Normalise job titles and company names for the given postings.

        Delegates to :class:`~agents.deduplication.DeduplicationAgent`, which
        batches postings and sends them to an LLM.  Postings that succeed will
        have :attr:`~models.collection_service.JobPosting.title_normalized` and
        :attr:`~models.collection_service.JobPosting.company_normalized` filled
        in; postings that exhaust all retries are captured in
        :attr:`~models.deduplication.NormalizationResult.failed`.

        Args:
            postings: Raw postings whose ``title`` and ``company`` fields have
                not yet been normalised.

        Returns:
            A :class:`~models.deduplication.NormalizationResult` with
            ``processed`` (normalised) and ``failed`` postings.
        """
        return await self.agent.normalize(postings)

    async def deduplicate(
        self,
        postings: list[JobPosting],
        within_days: int = 60,
    ) -> list[JobPosting]:
        """Remove duplicate postings within the current batch and against the store.

        Three-stage deduplication:

        1. **UID filter** – postings whose ``uid`` is already present in the
           repository are dropped (re-fetched in a previous run due to
           checkpoint overlap).
        2. **Intra-batch dedup** – among the remaining postings, those that
           share the same ``(title_normalized, company_normalized)`` key are
           collapsed into a single representative, keeping the most recently
           posted one.
        3. **Cross-run recency filter** – candidate keys are checked against
           stored postings with a matching normalised key whose ``posted_at``
           falls within the last *within_days* days.  A match means the role
           was advertised recently enough to be considered the same opening, so
           the new posting is dropped.

        Args:
            postings: Normalised postings (``title_normalized`` and
                ``company_normalized`` should be populated).
            within_days: Look-back window in days used for the cross-run
                recency filter.  A new posting is suppressed when a stored
                posting with the same normalised key was published within this
                many days.  Defaults to ``60``.

        Returns:
            Deduplicated list of postings sorted by ``posted_at`` descending.
        """
        uids = {p.uid for p in postings}
        existing_uids = await self.repo.get_existing_uids(uids)
        new_postings = [p for p in postings if p.uid not in existing_uids]

        # Intra-batch: for each canonical (title, company) key keep the most recently posted entry.
        seen: dict[tuple[str, str], JobPosting] = {}
        for posting in sorted(new_postings, key=lambda p: p.posted_at, reverse=True):
            key = (
                posting.title_normalized or posting.title,
                posting.company_normalized or posting.company,
            )
            if key not in seen:
                seen[key] = posting

        # Cross-run: drop any key that already has a recent match in the store.
        since = datetime.now(timezone.utc) - timedelta(days=within_days)
        stored_keys = await self.repo.get_recent_normalized_keys(set(seen.keys()), since)

        return [p for key, p in seen.items() if key not in stored_keys]

    async def get_normalized_jobs(self) -> CollectionResult:
        """Execute the collection, normalisation, and deduplication pipeline.

        Steps:

        1. :meth:`collect` – fetch new postings from all registered sources.
        2. :meth:`normalize` – canonicalise titles and company names via the AI
           agent.
        3. :meth:`deduplicate` – remove intra-batch and cross-run duplicates.

        Persistence and checkpoint management are intentionally left to the
        caller so that this method remains side-effect-free with respect to the
        backing store.

        Returns:
            A :class:`~models.collection_service.CollectionResult` containing
            the final deduplicated postings ready for downstream storage, plus a
            combined list of invalid entries (parse failures from
            :meth:`collect` and normalisation failures from :meth:`normalize`).
        """
        collection_result = await self.collect()
        normalization_result = await self.normalize(collection_result.postings)
        deduplicated = await self.deduplicate(normalization_result.processed)

        norm_failures = [
            InvalidEntry(entry=f.posting.model_dump(mode="json"), error=f.error)
            for f in normalization_result.failed
        ]

        return CollectionResult(
            postings=deduplicated,
            invalid_entries=collection_result.invalid_entries + norm_failures,
        )
