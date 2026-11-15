from app.core.config import Settings
from app.llm.base import LLMProvider
from .compatible_provider import CompatibleLLMProvider, UnconfiguredLLMProvider


def create_provider(settings: Settings) -> LLMProvider:
    if not settings.llm_base_url or not settings.llm_model:
        return UnconfiguredLLMProvider()
    return CompatibleLLMProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key,
                                 settings.llm_timeout_seconds)
