from datetime import datetime


class CollectionTimeoutError(Exception):
    """Raised when an API call exceeds the configured timeout."""

    def __init__(self, url: str = "", timeout_seconds: float | None = None) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        detail = f" after {timeout_seconds}s" if timeout_seconds is not None else ""
        super().__init__(f"API request timed out{detail}: {url}" if url else f"API request timed out{detail}")


class CollectionAPIError(Exception):
    """Raised when an API response returns a non-200 status code."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"API request failed with status code {status_code}")


class MissingEntriesError(Exception):
    """Raised when the earliest collected entry is more recent than min_date,
    indicating a gap in continuity rather than a complete collection."""

    def __init__(self, earliest_date: datetime, min_date: datetime) -> None:
        self.earliest_date = earliest_date.isoformat()
        self.min_date = min_date.isoformat()
        super().__init__(
            f"Collection is incomplete: earliest entry {self.earliest_date} "
            f"is later than min_date {self.min_date}")
