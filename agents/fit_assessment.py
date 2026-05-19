import json
from pathlib import Path

from pydantic_ai import Agent, BinaryContent, models

from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from models.users import UserProfile

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
        self.model = model
        self.agent: Agent[None, FitAssessment] = Agent(
            model=model,
            output_type=FitAssessment,
        )
        self._prompt_template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    async def assess(
        self,
        user_profile: UserProfile,
        cv: Path | bytes,
        job: JobPosting,
    ) -> FitAssessment:
        """Assess fit for *job* using *user_profile* and CV (*cv* as path or PDF bytes)."""
        prompt = self._build_prompt(user_profile, job)
        user_content: list[str | BinaryContent] = [
            prompt,
            self._cv_content(cv), ]

        result = await self.agent.run(user_content)
        return result.output

    def _build_prompt(self, user_profile: UserProfile, job: JobPosting) -> str:
        profile_json = user_profile.model_dump_json(indent=2)
        job_payload = json.dumps(
            job.model_dump(mode="json", include=set(_JOB_FIELDS)),
            indent=2,
        )
        return self._prompt_template.format(
            user_profile=profile_json,
            job_posting=job_payload,
        )

    @staticmethod
    def _cv_content(cv: Path | bytes) -> BinaryContent:
        if isinstance(cv, Path):
            return BinaryContent.from_path(cv)
        return BinaryContent(data=cv, media_type="application/pdf")
