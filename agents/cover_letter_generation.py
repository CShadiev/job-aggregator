"""AI agent for generating personalized cover letters."""

import json
from pathlib import Path

from pydantic_ai import Agent, models

from models.collection_service import JobPosting
from models.fit_assessment import CoverLetterContent, FitAssessment
from models.users import UserProfile

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_templates" / "cover_letter_generation.md"

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


class CoverLetterGenerationAgent:
    """Generates a tailored cover letter from a profile, posting and fit assessment."""

    def __init__(self, model: models.Model):
        """Initialize the cover letter generation agent with a model and prompt template.

        Args:
            model: PydanticAI model instance.
        """
        self.model = model
        self.agent: Agent[None, CoverLetterContent] = Agent(
            model=model,
            output_type=CoverLetterContent,
        )
        self._prompt_template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    async def generate(
        self,
        user_profile: UserProfile,
        job: JobPosting,
        fit_assessment: FitAssessment,
    ) -> CoverLetterContent:
        """Generate a structured cover letter for *job* using *user_profile* and *fit_assessment*."""
        prompt = self._build_generation_prompt(user_profile, job, fit_assessment)
        result = await self.agent.run(prompt)
        return result.output

    def _build_generation_prompt(
        self,
        user_profile: UserProfile,
        job: JobPosting,
        fit_assessment: FitAssessment,
    ) -> str:
        """Construct the prompt string by combining profile, job posting, and assessment payloads."""
        profile_json = user_profile.model_dump_json(indent=2)
        job_payload = json.dumps(
            job.model_dump(mode="json", include=set(_JOB_FIELDS)),
            indent=2,
        )
        assessment_json = fit_assessment.model_dump_json(indent=2)
        return self._prompt_template.format(
            user_profile=profile_json,
            job_posting=job_payload,
            fit_assessment=assessment_json,
        )
