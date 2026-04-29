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
