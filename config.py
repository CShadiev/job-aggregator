import os
from typing import Optional
from pydantic import BaseModel, ConfigDict


class _Config(BaseModel):
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

    APIFY_INDEED_TASK_ID: str | None = None
    APIFY_STEPSTONE_TASK_ID: str | None = None

    DEDUPLICATION_BATCH_SIZE: int = 50
    DEDUPLICATION_MAX_RETRIES: int = 3

    FIT_ASSESSMENT_MAX_RETRIES: int = 3

    DEBUG_MODE: bool = False
    LOG_DIR: str = "logs"

    OPENAI_API_KEY: str

    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "job_aggregator"
    MONGODB_JOBS_COLLECTION: str = "jobs"
    MONGODB_CHECKPOINTS_COLLECTION: str = "checkpoints"
    MONGODB_PROCESSING_COLLECTION: str = "job_processing"
    MONGODB_FAILED_COLLECTION: str = "failed_entries"


class ConfigProvider:
    '''
    Singleton class for providing application configuration.
    Implements lazy loading of configuration from environment variables.
    '''
    __config: Optional[_Config] = None

    @classmethod
    def get_config(cls) -> _Config:
        '''
        Get the application configuration.
        Configuration is only loaded once, subsequent calls return the
        cached instance.
        '''
        if cls.__config is None:
            cls.__config = cls.__load_config()
        return cls.__config

    @classmethod
    def __load_config(cls) -> _Config:
        '''
        Load the application configuration from environment variables.
        '''
        # try to load the config from .env file
        try:
            from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
            load_dotenv(override=True)
            config = _Config.model_validate(os.environ)
            return config
        except ImportError:
            # if the dotenv package is not installed,
            #   load the config from the environment variables
            config = _Config.model_validate(os.environ)
            return config
