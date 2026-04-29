"""Reusable Pydantic field validators for the models layer."""

from datetime import datetime, timezone


def ts_validator(v: datetime) -> datetime:
    """Normalise a datetime to UTC.

    Timezone-naive values are assumed to already be in UTC and are made
    timezone-aware by attaching :attr:`datetime.timezone.utc`.  Timezone-aware
    values are converted to UTC via :meth:`datetime.astimezone`.

    Args:
        v: The raw datetime value produced by Pydantic's initial parsing.

    Returns:
        A timezone-aware :class:`datetime` in UTC.
    """
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)
