"""Shared helpers for the hosted demo account."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from config import ConfigProvider
from models.users import UserProfile

DEMO_PROFILE_PATH = Path(__file__).resolve().parent / "fixtures" / "demo" / "profile.json"
DEMO_PIPELINE_THREAD_ID = "demo-pipeline"
DEMO_LOGIN_BODY_REJECTED = "Demo login does not accept credentials in the request body"
DAILY_MANUAL_JOB_LIMIT_DETAIL = "Daily demo limit reached for manual job submissions"
DAILY_COVER_LETTER_LIMIT_DETAIL = "Daily demo limit reached for cover letter generation"
DEMO_MANUAL_JOB_URL_HOSTS = ("linkedin.com", "arbeitnow.com", "indeed.com")
DEMO_MANUAL_JOB_URL_REJECTED = "Demo job URLs must be https links to LinkedIn, Arbeitnow, or Indeed"


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


def is_allowed_demo_job_url(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = DEMO_MANUAL_JOB_URL_HOSTS,
) -> bool:
    """Return True when *url* is https and its host is an allowed job board.

    The check is suffix-safe: ``linkedin.com.evil.com`` is rejected.
    Userinfo, non-https schemes, and non-443 ports are rejected so a
    visitor cannot be sent to an unexpected origin.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or parsed.port not in (None, 443):
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_hosts)
