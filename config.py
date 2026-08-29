import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_APP_ROOT = Path(__file__).resolve().parent


class Config(BaseSettings):
    '''
    Settings class for application configuration.
    Implements environment variable loading and validation.
    Should only be accessed through the ConfigProvider class.
    '''
    model_config = SettingsConfigDict(frozen=True, env_file=".env", extra="ignore")

    APIFY_API_KEY: str
    APIFY_BASE_URL: str = "https://api.apify.com/v2"

    ARBEITNOW_BASE_URL: str = "https://www.arbeitnow.com/api/job-board-api"
    ARBEITNOW_MAX_PAGES: int = 10

    APIFY_INDEED_TASK_ID: str = "hopeful_quarter~indeed-scraper-task"
    APIFY_STEPSTONE_TASK_ID: str = "hopeful_quarter~stepstone-job-scraper-task"
    APIFY_LINKEDIN_TASK_ID: str = "hopeful_quarter~linkedin-scraper-task"  # DE
    APIFY_LINKEDIN_UK_TASK_ID: str = "hopeful_quarter~linkedin-scraper-united-kingdom"
    APIFY_LINKEDIN_PL_TASK_ID: str = "hopeful_quarter~linkedin-scraper-poland"

    DEDUPLICATION_BATCH_SIZE: int = 50
    DEDUPLICATION_MAX_RETRIES: int = 3
    DEDUPLICATION_MODEL: str = "gpt-5.6-luna"

    FIT_ASSESSMENT_MAX_RETRIES: int = 3

    DEBUG_MODE: bool = False

    LOG_DIR: str = str(_APP_ROOT / "logs")
    TEMP_DIR: str = str(_APP_ROOT / "tmp")

    @field_validator("LOG_DIR", "TEMP_DIR", mode="before")
    @classmethod
    def resolve_absolute_dir(cls, value: object) -> str:
        '''Resolve directory settings to absolute paths.

        Relative values are interpreted against the application root so the
        process working directory cannot redirect logs or temp files.
        Absolute values (including paths outside the app root) are kept.
        '''
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = _APP_ROOT / path
        return str(path.resolve())

    OPENAI_API_KEY: str
    DEEPINFRA_API_KEY: str
    GROK_API_KEY: str

    MONGODB_HOST: str = "localhost"
    MONGODB_PORT: int = 27017
    MONGODB_USER: str
    MONGODB_PASSWORD: str

    MONGODB_DATABASE: str = "job_aggregator"
    MONGODB_TEST_DATABASE: str = "job_aggregator_test"
    MONGODB_JOBS_COLLECTION: str = "jobs"
    MONGODB_CHECKPOINTS_COLLECTION: str = "checkpoints"
    MONGODB_PROCESSING_COLLECTION: str = "job_processing"
    MONGODB_FAILED_COLLECTION: str = "failed_entries"
    MONGODB_USER_PROFILES_COLLECTION: str = "user_profiles"
    MONGODB_ASSESSMENTS_COLLECTION: str = "assessments"
    MONGODB_JOB_APPLICATIONS_COLLECTION: str = "job_applications"
    MONGODB_SCREENINGS_COLLECTION: str = "screenings"
    MONGODB_FAILED_TASKS_COLLECTION: str = "failed_tasks"
    MONGODB_LANGGRAPH_CHECKPOINT_COLLECTION: str = "langgraph_checkpoints"
    MONGODB_LANGGRAPH_WRITES_COLLECTION: str = "langgraph_checkpoint_writes"

    SCREENING_MODEL: str = "gpt-5.6-luna"
    FIT_ASSESSMENT_MODEL: str = "gpt-5-mini"
    COVER_LETTER_MODEL: str = "gpt-5-mini"
    COVER_LETTER_MIN_CV_SCORE: float = 80
    PIPELINE_PAIR_CONCURRENCY: int = 10
    PIPELINE_THREAD_ID: str = "job-pipeline"
    PIPELINE_SCHEDULE_SECONDS: int = 60 * 60 * 12

    S3_ENDPOINT_URL: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_REGION: str
    S3_BUCKET_NAME: str

    AUTH0_DOMAIN: str
    AUTH0_CLIENT_ID: str
    AUTH0_CLIENT_SECRET: str
    AUTH0_AUDIENCE: str

    FASTAPI_HOST: str = "0.0.0.0"
    FASTAPI_PORT: int = 8000
    FASTAPI_RELOAD: bool = False
    FASTAPI_ROOT_PATH: str = ""

    ALLOWED_ORIGINS: list[str] = ["https://cshadiev.dev"]


class ConfigProvider:
    '''
    Singleton class for providing application configuration.
    Implements lazy loading of configuration from environment variables.
    '''
    __config: Optional[Config] = None

    @classmethod
    def get_config(cls) -> Config:
        '''
        Get the application configuration.
        Configuration is only loaded once, subsequent calls return the
        cached instance.
        '''
        if cls.__config is None:
            cls.__config = cls.__load_config()
        return cls.__config

    @classmethod
    def __load_config(cls) -> Config:
        '''
        Load the application configuration from environment variables.
        '''
        # try to load the config from .env file
        return Config.model_validate({})
