from typing import Callable, Dict

from .base import BaseLLMProvider
from .ollama_provider import OllamaProvider
from .openrouter_provider import OpenRouterProvider
from .google_ai_studio_provider import GoogleAIStudioProvider
from .huggingface_provider import HuggingFaceProvider

ProviderFactory = Callable[[dict], BaseLLMProvider]
PROVIDER_FACTORIES: Dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register a provider factory without changing the orchestrator."""
    if not name or not callable(factory):
        raise ValueError("A provider name and callable factory are required.")
    PROVIDER_FACTORIES[name] = factory


def get_provider_factory(name: str) -> ProviderFactory:
    try:
        return PROVIDER_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {name}") from exc


def _ollama(config: dict) -> BaseLLMProvider:
    return OllamaProvider(base_url=config.get("base_url", "http://localhost:11434"))


def _openrouter(config: dict) -> BaseLLMProvider:
    return OpenRouterProvider(
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", "https://openrouter.ai/api/v1"),
    )


register_provider("ollama", _ollama)
register_provider("openrouter", _openrouter)

def _google_ai_studio(config: dict) -> BaseLLMProvider:
    return GoogleAIStudioProvider(
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", "https://generativelanguage.googleapis.com/v1beta"),
    )


def _huggingface(config: dict) -> BaseLLMProvider:
    return HuggingFaceProvider(
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", "https://router.huggingface.co/v1"),
    )


register_provider("google_ai_studio", _google_ai_studio)
register_provider("huggingface", _huggingface)
