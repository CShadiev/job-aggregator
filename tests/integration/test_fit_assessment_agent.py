from pathlib import Path
from agents.fit_assessment import FitAssessmentAgent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from config import ConfigProvider
from models.collection_service import JobPosting
from models.fit_assessment import FitAssessment
from logger_provider import LoggerProvider
import json
import pytest

from models.users import UserProfile

config = ConfigProvider.get_config()
log = LoggerProvider.get_logger()


def create_fit_assessment_agent() -> FitAssessmentAgent:
    model = OpenAIChatModel(model_name="gpt-5-mini", provider=OpenAIProvider(api_key=config.OPENAI_API_KEY))
    return FitAssessmentAgent(model)


def load_user_profile() -> UserProfile:
    with open("tests/datasets/sample_user_profile.json", "r") as f:
        entries = json.load(f)
        return UserProfile.model_validate(entries)


def load_job_postings() -> list[JobPosting]:
    with open("tests/datasets/sample_job_postings.json", "r") as f:
        entries = json.load(f)
        return [JobPosting.model_validate(entry) for entry in entries]


@pytest.mark.priced
async def test_fit_assessment_agent():
    agent = create_fit_assessment_agent()
    user_profile = load_user_profile()
    job_postings = load_job_postings()
    for i, job_posting in enumerate(job_postings):
        log.info(f"Assessing job posting {i+1} of {len(job_postings)}")
        result = await agent.assess(user_profile, Path("tests/datasets/Chingiz_Shadiev_CV.pdf"), job_posting)
        assert result is not None
        assert isinstance(result, FitAssessment)
        log.info(f"Score: {result.cv_ats_match_score}", assessment=result.model_dump(mode="json"))
