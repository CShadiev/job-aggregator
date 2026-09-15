"""AI agent for screening job postings against candidate CVs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pydantic_ai import Agent, models

from agents.fit_assessment import _JOB_FIELDS
from models.collection_service import JobPosting
from models.screening import ScreeningAgentOutput, ScreeningResult
from monitoring.metrics import record_agent_usage

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_templates" / "screening.md"


@dataclass(frozen=True)
class CachedScreeningPrompt:
    """Constant prefix, CV slot, then variable job suffix — cacheable leading bytes."""

    prefix: str
    between: str
    suffix: str


def parse_cached_screening_prompt(template: str) -> CachedScreeningPrompt | None:
    """Return a cacheable layout when ``{cv_text}`` precedes ``{job_posting}``.

    A template with only ``{job_posting}`` is the isolated Phase 1c shape:
    formatted prompt first, CV text as a trailing content part. That keeps the
    representation change measurable without also reordering.
    """
    cv_at = template.find("{cv_text}")
    job_at = template.find("{job_posting}")
    if job_at < 0:
        raise ValueError("Screening prompt must contain {job_posting}")
    if cv_at < 0:
        return None
    if cv_at > job_at:
        raise ValueError("Screening prompt must contain {cv_text} before {job_posting}")
    prefix, _, remainder = template.partition("{cv_text}")
    between, _, suffix = remainder.partition("{job_posting}")
    return CachedScreeningPrompt(prefix=prefix, between=between, suffix=suffix)


class ScreeningAgent:
    """Screens a job posting using CV only — whether full fit assessment is worthwhile."""

    def __init__(
        self,
        model: models.Model,
        *,
        prompt_template_path: Path | None = None,
    ):
        """Initialize the screening agent with a model and prompt template.

        Args:
            model: PydanticAI model instance.
            prompt_template_path: Optional override used by isolated benchmark runs.
        """
        self.model = model
        self.agent: Agent[None, ScreeningAgentOutput] = Agent(
            model=model,
            output_type=ScreeningAgentOutput,
        )
        path = prompt_template_path or _PROMPT_TEMPLATE_PATH
        self.prompt_template_path = path
        self._prompt_template = path.read_text(encoding="utf-8")
        self._cached_prompt = parse_cached_screening_prompt(self._prompt_template)

    def build_user_content(self, cv_text: str, job: JobPosting) -> list[str]:
        """Assemble the user message with the CV text and variable job payload."""
        job_payload = self._build_job_payload(job)
        if self._cached_prompt is None:
            return [self._prompt_template.format(job_posting=job_payload), cv_text]
        return [
            self._cached_prompt.prefix,
            cv_text,
            f"{self._cached_prompt.between}{job_payload}{self._cached_prompt.suffix}",
        ]

    async def screen(self, cv_text: str, job: JobPosting) -> ScreeningResult:
        """Screen *job* using only the layout-faithful CV rendering."""
        start = perf_counter()
        result = await self.agent.run(self.build_user_content(cv_text, job))
        usage = result.usage
        await record_agent_usage(
            agent_name="screening",
            model_name=self.model.model_name,
            usage=usage,
            duration_seconds=perf_counter() - start,
        )
        output = result.output
        return ScreeningResult(
            worth_full_assessment=bool(output.worth_full_assessment),
            confidence=output.confidence,
            input_tokens=int(usage.input_tokens or 0),
            output_tokens=int(usage.output_tokens or 0),
            cache_read_tokens=int(usage.cache_read_tokens or 0),
        )

    @staticmethod
    def _build_job_payload(job: JobPosting) -> str:
        """Serialize the variable job payload placed last for prefix caching."""
        return json.dumps(
            job.model_dump(mode="json", include=set(_JOB_FIELDS)),
            indent=2,
        )
