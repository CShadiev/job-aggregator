"""Tests for screening prompt packaging and the closed model rate card."""

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from agents.model_factory import Model
from agents.screening import ScreeningAgent, parse_cached_screening_prompt
from monitoring.pricing import DEFAULT_RATES
from tests.helpers.job_posting import make_job_posting

_PRODUCTION = Path("agents/prompt_templates/screening.md")
_ISOLATED = Path("benchmarks/screening/prompts/text_isolated.md")


class TestParseCachedScreeningPrompt:
    """Tests for detecting the cacheable constant-then-variable layout."""

    def test_production_template_is_cacheable(self):
        """Verify the production prompt puts CV text before the job payload."""
        layout = parse_cached_screening_prompt(_PRODUCTION.read_text(encoding="utf-8"))
        assert layout is not None
        assert "{cv_text}" not in layout.prefix
        assert "{job_posting}" not in layout.prefix
        assert layout.between.strip().startswith("## JOB POSTING")

    def test_isolated_template_is_not_cacheable(self):
        """Verify the Phase 1c prompt keeps the original job-then-CV order."""
        assert parse_cached_screening_prompt(_ISOLATED.read_text(encoding="utf-8")) is None

    def test_cv_after_job_is_rejected(self):
        """Verify a reversed placeholder order cannot silently ship."""
        with pytest.raises(ValueError, match="before \\{job_posting\\}"):
            parse_cached_screening_prompt("{job_posting}\n{cv_text}")


class TestBuildUserContent:
    """Tests for the assembled user-message parts."""

    def test_production_layout_is_prefix_cv_then_job(self):
        """Verify production packaging is constant prefix, CV, variable job."""
        agent = ScreeningAgent(TestModel(), prompt_template_path=_PRODUCTION)
        job = make_job_posting(title="Staff Backend Engineer")
        parts = agent.build_user_content("# Ada CV", job)
        assert len(parts) == 3
        assert "Staff Backend Engineer" not in parts[0]
        assert parts[1] == "# Ada CV"
        assert "Staff Backend Engineer" in parts[2]
        assert parts[2].index("Staff Backend Engineer") > parts[2].index("JOB POSTING")

    def test_isolated_layout_keeps_job_before_cv(self):
        """Verify the isolated prompt still sends the job payload before the CV."""
        agent = ScreeningAgent(TestModel(), prompt_template_path=_ISOLATED)
        job = make_job_posting(title="Staff Backend Engineer")
        parts = agent.build_user_content("# Ada CV", job)
        assert len(parts) == 2
        assert "Staff Backend Engineer" in parts[0]
        assert parts[1] == "# Ada CV"


class TestModelRateCardCoverage:
    """Tests that the closed model enum cannot silently benchmark as free."""

    def test_every_registered_model_has_a_static_rate(self):
        """Verify DEFAULT_RATES covers every Model enum member used by the CLI."""
        missing = [member.value for member in Model if member.value not in DEFAULT_RATES]
        assert missing == []
