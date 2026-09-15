"""AI agent for deep candidate fit assessment against job postings."""

import json
from pathlib import Path
from time import perf_counter

from pydantic_ai import Agent, models

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.users import UserProfile
from monitoring.metrics import record_agent_usage

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_templates" / "fit_assessment.md"

_JOB_FIELDS = (
    "uid",
    "source",
    "title",
    "company",
    "location",
    "remote",
    "url",
    "tags",
    "description_raw",
    "job_types",
    "posted_at",
)


class FitAssessmentAgent:
    """Assesses candidate fit for a job using CV and profile against a posting."""

    def __init__(self, model: models.Model):
        """Initialize the fit assessment agent with a model and prompt template.

        Args:
            model: PydanticAI model instance.
        """
        self.model = model
        self.agent: Agent[None, FitAssessment] = Agent(
            model=model,
            output_type=FitAssessment,
        )
        self._prompt_template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        prefix, cv_marker, remainder = self._prompt_template.partition("{cv_text}")
        between, job_marker, suffix = remainder.partition("{job_posting}")
        if not cv_marker or not job_marker:
            raise ValueError("Fit prompt must contain {cv_text} before {job_posting}")
        self._prompt_prefix = prefix
        self._prompt_between = between
        self._prompt_suffix = suffix

    async def assess(
        self,
        user_profile: UserProfile,
        cv_text: str,
        job: JobPosting,
    ) -> FitAssessment:
        """Assess fit for *job* using *user_profile* and a CV text rendering."""
        assessment, _, _ = await self.assess_with_usage(user_profile, cv_text, job)
        return assessment

    async def assess_with_usage(
        self,
        user_profile: UserProfile,
        cv_text: str,
        job: JobPosting,
    ) -> tuple[FitAssessment, int, int]:
        """Assess fit and return ``(assessment, input_tokens, output_tokens)``.

        Token counts stay off :class:`FitAssessment` so they are not persisted
        to Mongo or OpenSearch.
        """
        prompt_prefix, job_suffix = self._build_assessment_prompt(user_profile, job)
        user_content = [
            prompt_prefix,
            cv_text,
            job_suffix,
        ]

        start = perf_counter()
        result = await self.agent.run(user_content)
        usage = result.usage
        await record_agent_usage(
            agent_name="fit_assessment",
            model_name=self.model.model_name,
            usage=usage,
            duration_seconds=perf_counter() - start,
        )
        return (
            result.output,
            int(usage.input_tokens or 0),
            int(usage.output_tokens or 0),
        )

    def _build_assessment_prompt(
        self, user_profile: UserProfile, job: JobPosting
    ) -> tuple[str, str]:
        """Build a stable candidate prefix and variable job suffix."""
        profile_json = user_profile.model_dump_json(indent=2)
        job_payload = json.dumps(
            job.model_dump(mode="json", include=set(_JOB_FIELDS)),
            indent=2,
        )
        return (
            self._prompt_prefix.replace("{user_profile}", profile_json),
            f"{self._prompt_between}{job_payload}{self._prompt_suffix}",
        )
