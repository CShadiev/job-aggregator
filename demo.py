"""Shared helpers for the hosted demo account."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import ConfigProvider
from models.users import UserProfile

DEMO_PROFILE_PATH = Path(__file__).resolve().parent / "fixtures" / "demo" / "profile.json"
DEMO_PIPELINE_THREAD_ID = "demo-pipeline"
DEMO_LOGIN_BODY_REJECTED = "Demo login does not accept credentials in the request body"
DAILY_MANUAL_JOB_LIMIT_DETAIL = "Daily demo limit reached for manual job submissions"
DAILY_COVER_LETTER_LIMIT_DETAIL = "Daily demo limit reached for cover letter generation"


def load_demo_profile(path: Path | None = None) -> UserProfile:
    """Load and validate the committed demo ``UserProfile`` fixture."""
    target = path or DEMO_PROFILE_PATH
    return UserProfile.model_validate_json(target.read_text(encoding="utf-8"))


def configured_demo_username() -> str | None:
    """Return the configured demo username, or None when demo hosting is off."""
    return ConfigProvider.get_config().DEMO_USERNAME


def utc_calendar_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` of the UTC calendar day containing *now*."""
    current = now or datetime.now(UTC)
    start = datetime(current.year, current.month, current.day, tzinfo=UTC)
    return start, start + timedelta(days=1)
