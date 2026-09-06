"""Factory and registry for LLM models used by PydanticAI agents."""

from enum import StrEnum

from pydantic_ai.models import Model as PydanticModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from config import ConfigProvider

config = ConfigProvider.get_config()

GROK_PROVIDER = OpenAIProvider(api_key=config.GROK_API_KEY, base_url="https://api.x.ai/v1")
OPENAI_PROVIDER = OpenAIProvider(
    api_key=config.OPENAI_API_KEY, base_url="https://api.openai.com/v1"
)


class Model(StrEnum):
    """Supported model identifiers across providers."""

    GROK_4_3 = "grok-4.3"
    GROK_4_5 = "grok-4.5"
    LUNA_5_6 = "gpt-5.6-luna"
    GPT_5_MINI = "gpt-5-mini"


class ModelFactory:
    """Provides cached instances of configured PydanticAI models."""

    _models: dict[Model, PydanticModel] = {
        Model.GROK_4_3: OpenAIResponsesModel(model_name=Model.GROK_4_3, provider=GROK_PROVIDER),
        Model.GROK_4_5: OpenAIResponsesModel(model_name=Model.GROK_4_5, provider=GROK_PROVIDER),
        Model.LUNA_5_6: OpenAIResponsesModel(model_name=Model.LUNA_5_6, provider=OPENAI_PROVIDER),
        Model.GPT_5_MINI: OpenAIResponsesModel(
            model_name=Model.GPT_5_MINI, provider=OPENAI_PROVIDER
        ),
    }

    @classmethod
    def get_model(cls, model: Model) -> PydanticModel:
        """Retrieve a configured PydanticAI Model instance by enum key.

        Args:
            model: The target Model identifier.

        Returns:
            The configured PydanticModel instance.

        Raises:
            ValueError: If the requested model is not found in the factory registry.
        """
        try:
            return cls._models[model]
        except KeyError as e:
            raise ValueError(f"Model {model} not found") from e
