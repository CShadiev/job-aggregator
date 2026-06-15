import pytest
from pathlib import Path
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from agents.cover_letter_generation import CoverLetterGenerationAgent
from config import ConfigProvider
from models.fit_assessment import CoverLetterContent
from tests.datasets.cover_letter_sample import (
    make_sample_fit_assessment,
    make_sample_job_posting,
    make_sample_user_profile,
)
from logger_provider import LoggerProvider
from tools.pdf_generator import generate_cover_letter

log = LoggerProvider.get_logger()


def get_sample_cover_letter_content():
    path = Path("tests") / "datasets" / "sample_cover_letter.json"
    return CoverLetterContent.model_validate_json(path.read_text())


@pytest.mark.priced
async def test_cover_letter_generation_happy_path():
    config = ConfigProvider.get_config()
    model = OpenAIChatModel(model_name="gpt-5-mini", provider=OpenAIProvider(api_key=config.OPENAI_API_KEY))
    agent = CoverLetterGenerationAgent(model=model)

    result = await agent.generate(
        user_profile=make_sample_user_profile(),
        job=make_sample_job_posting(),
        fit_assessment=make_sample_fit_assessment(),
    )

    assert isinstance(result, CoverLetterContent)
    log.info(f"Cover letter generated: {result.model_dump_json(indent=2)}")


async def test_pdf_from_cover_letter_content():
    cover_letter_content = get_sample_cover_letter_content()
    pdf_path = Path("tests") / "datasets" / "sample_cover_letter.pdf"

    generate_cover_letter(cover_letter_content, str(pdf_path))
    assert pdf_path.exists()
