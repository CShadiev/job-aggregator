"""AI agent for deduplication and canonical normalization of job postings."""

import asyncio
import json
from pathlib import Path

from pydantic_ai import Agent, models

from config import ConfigProvider
from models.collection_service import JobPosting
from models.deduplication import FailedJobPosting, NormalizationResult, NormalizedBatch

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_templates" / "normalize_job.md"
CONFIG = ConfigProvider.get_config()


class DeduplicationAgent:
    """Agent that extracts and normalizes canonical job titles and company names using an LLM."""

    def __init__(self, model: models.Model):
        """Initialize the deduplication agent with a model and prompt template.

        Args:
            model: PydanticAI model instance.
        """
        self.model = model
        self.agent: Agent[None, NormalizedBatch] = Agent(
            model=model,
            output_type=NormalizedBatch,
        )
        self._prompt_template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    async def normalize(
        self, postings: list[JobPosting], batch_size: int = CONFIG.DEDUPLICATION_BATCH_SIZE
    ) -> NormalizationResult:
        """Normalize job titles and company names for each posting.

        Postings are split into fixed-size batches (``DEDUPLICATION_BATCH_SIZE``)
        and processed concurrently.

        Args:
            postings: List of JobPosting instances to normalize.
            batch_size: Batch size for chunking postings before sending to the agent.

        Returns:
            NormalizationResult containing processed and failed postings.
        """
        batches = [postings[i : i + batch_size] for i in range(0, len(postings), batch_size)]

        results = await asyncio.gather(*[self._process_batch(batch) for batch in batches])

        processed: list[JobPosting] = []
        failed: list[FailedJobPosting] = []
        for batch_processed, batch_failed in results:
            processed.extend(batch_processed)
            failed.extend(batch_failed)

        return NormalizationResult(processed=processed, failed=failed)

    async def _process_batch(
        self,
        batch: list[JobPosting],
    ) -> tuple[list[JobPosting], list[FailedJobPosting]]:
        """Run one batch through the AI agent."""
        temp_map: dict[str, JobPosting] = {str(i): posting for i, posting in enumerate(batch)}

        jobs_payload = json.dumps(
            [{"id": k, "title": v.title, "company": v.company} for k, v in temp_map.items()],
            indent=2,
        )
        prompt = self._prompt_template.format(jobs_to_process=jobs_payload)

        try:
            result = await self.agent.run(prompt)
            return self._reconcile(temp_map, result.output)
        except Exception as exc:
            error = str(exc)
            return [], [FailedJobPosting(posting=posting, error=error) for posting in batch]

    def _reconcile(
        self,
        temp_map: dict[str, JobPosting],
        normalized: NormalizedBatch,
    ) -> tuple[list[JobPosting], list[FailedJobPosting]]:
        """Map AI-returned normalized entries back to original JobPosting objects."""
        processed: list[JobPosting] = []
        failed: list[FailedJobPosting] = []
        seen_ids: set[str] = set()

        for entry in normalized.jobs:
            original = temp_map.get(entry.id)
            if original is None or entry.id in seen_ids:
                continue
            seen_ids.add(entry.id)
            processed.append(
                original.model_copy(
                    update={
                        "title_normalized": entry.title.lower(),
                        "company_normalized": entry.company.lower(),
                    }
                )
            )

        for temp_id, posting in temp_map.items():
            if temp_id not in seen_ids:
                failed.append(
                    FailedJobPosting(
                        posting=posting,
                        error="AI did not return a result for this posting.",
                    )
                )

        return processed, failed
