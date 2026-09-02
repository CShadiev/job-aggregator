import json
from pathlib import Path

from pydantic_ai import Agent, BinaryContent, models

from agents.fit_assessment import _JOB_FIELDS
from models.collection_service import JobPosting
from models.screening import ScreeningAgentOutput, ScreeningResult

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_templates" / "screening.md"


class ScreeningAgent:
    """Screens a job posting using CV only — whether full fit assessment is worthwhile."""

    def __init__(self, model: models.Model):
        self.model = model
        self.agent: Agent[None, ScreeningAgentOutput] = Agent(
            model=model,
            output_type=ScreeningAgentOutput,
        )
        self._prompt_template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    async def screen(self, cv: Path | bytes, job: JobPosting) -> ScreeningResult:
        """Screen *job* using CV only (*cv* as path or PDF bytes)."""
        prompt = self._build_screening_prompt(job)
        user_content: list[str | BinaryContent] = [
            prompt,
            self._cv_content(cv),
        ]

        result = await self.agent.run(user_content)
        output = result.output
        return ScreeningResult(
            worth_full_assessment=bool(output.worth_full_assessment),
            confidence=output.confidence,
        )

    def _build_screening_prompt(self, job: JobPosting) -> str:
        job_payload = json.dumps(
            job.model_dump(mode="json", include=set(_JOB_FIELDS)),
            indent=2,
        )
        return self._prompt_template.format(job_posting=job_payload)

    @staticmethod
    def _cv_content(cv: Path | bytes) -> BinaryContent:
        if isinstance(cv, Path):
            return BinaryContent.from_path(cv)
        return BinaryContent(data=cv, media_type="application/pdf")
