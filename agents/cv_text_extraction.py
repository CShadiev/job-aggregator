"""One-time LLM extraction of layout-faithful text from candidate CV PDFs."""

from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, models

from monitoring.metrics import record_agent_usage

_PROMPT_PATH = Path(__file__).parent / "prompt_templates" / "cv_text_extraction.md"


class CVTextExtractionOutput(BaseModel):
    """Structured output carrying the lossless CV rendering."""

    cv_text: str = Field(min_length=1)


class CVTextExtractionAgent:
    """Render a CV PDF as text without summarizing or adding information."""

    def __init__(self, model: models.Model):
        self.model = model
        self.agent: Agent[None, CVTextExtractionOutput] = Agent(
            model=model,
            output_type=CVTextExtractionOutput,
        )
        self._prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    async def extract(self, cv: bytes) -> str:
        """Return a layout-annotated, content-faithful rendering of *cv*."""
        start = perf_counter()
        result = await self.agent.run(
            [
                self._prompt,
                BinaryContent(data=cv, media_type="application/pdf"),
            ]
        )
        await record_agent_usage(
            agent_name="cv_extraction",
            model_name=self.model.model_name,
            usage=result.usage,
            duration_seconds=perf_counter() - start,
        )
        return result.output.cv_text.strip()
