"""Tests for the demo manual-submit URL allowlist."""

import pytest

from demo import is_allowed_demo_job_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/123",
        "https://linkedin.com/jobs/view/123",
        "https://de.linkedin.com/jobs/view/123",
        "https://www.arbeitnow.com/jobs/python-berlin",
        "https://arbeitnow.com/jobs/python-berlin",
        "https://www.indeed.com/viewjob?jk=abc",
        "https://de.indeed.com/viewjob?jk=abc",
        "https://www.linkedin.com/jobs/view/123.",
    ],
)
def test_allowlisted_https_job_board_urls_are_accepted(url: str):
    """Subdomains of the three boards are allowed over https."""
    assert is_allowed_demo_job_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.linkedin.com/jobs/view/123",
        "https://example.com/jobs/1",
        "https://linkedin.com.evil.com/jobs/view/123",
        "https://evil-linkedin.com/jobs/view/123",
        "https://notindeed.com/viewjob",
        "javascript:alert(1)",
        "https://linkedin.com:8443/jobs/view/123",
        "https://user@linkedin.com/jobs/view/123",
        "https://user:pass@www.indeed.com/viewjob",
        "",
        "not-a-url",
    ],
)
def test_non_allowlisted_urls_are_rejected(url: str):
    """Lookalike hosts, other schemes, userinfo, and odd ports are refused."""
    assert is_allowed_demo_job_url(url) is False
