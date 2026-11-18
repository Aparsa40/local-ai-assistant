from typing import Callable, Dict

from .base import BaseLLMProvider
from .ollama_provider import OllamaProvider
from .openrouter_provider import OpenRouterProvider

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
