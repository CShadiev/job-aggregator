import os
from typing import Optional
from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    '''
    Settings class for application configuration.
    Implements environment variable loading and validation.
    Should only be accessed through the ConfigProvider class.
    '''
    model_config = ConfigDict(frozen=True)

    APIFY_API_KEY: str
    APIFY_BASE_URL: str = "https://api.apify.com/v2"

    ARBEITNOW_BASE_URL: str = "https://www.arbeitnow.com/api/job-board-api"
    ARBEITNOW_MAX_PAGES: int = 10

    APIFY_INDEED_TASK_ID: str = "hopeful_quarter~indeed-scraper-task"
    APIFY_STEPSTONE_TASK_ID: str = "hopeful_quarter~stepstone-job-scraper-task"
    APIFY_LINKEDIN_TASK_ID: str = "hopeful_quarter~linkedin-scraper-task"

    DEDUPLICATION_BATCH_SIZE: int = 50
    DEDUPLICATION_MAX_RETRIES: int = 3

    FIT_ASSESSMENT_MAX_RETRIES: int = 3

    DEBUG_MODE: bool = False
    LOG_DIR: str = "logs"

    OPENAI_API_KEY: str

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
        try:
            from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
            load_dotenv(override=True)
            config = Config.model_validate(os.environ)
            return config
        except ImportError:
            # if the dotenv package is not installed,
            #   load the config from the environment variables
            config = Config.model_validate(os.environ)
            return config
