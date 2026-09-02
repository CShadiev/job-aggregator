from datetime import datetime
from typing import Protocol


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
