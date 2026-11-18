from core.providers.registry import PROVIDER_FACTORIES, get_provider_factory, register_provider
from core.providers.ollama_provider import OllamaProvider
from core.providers.openrouter_provider import OpenRouterProvider


def test_builtin_providers_are_registered():
    assert {"ollama", "openrouter"}.issubset(PROVIDER_FACTORIES)


def test_ollama_factory_uses_configured_base_url():
    provider = get_provider_factory("ollama")({"base_url": "http://127.0.0.1:11434"})
    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://127.0.0.1:11434"


def test_openrouter_factory_normalizes_api_url():
    provider = get_provider_factory("openrouter")({"base_url": "https://openrouter.ai", "api_key": "test"})
    assert isinstance(provider, OpenRouterProvider)
    assert provider.base_url == "https://openrouter.ai/api/v1"


def test_unknown_provider_fails_clearly():
    try:
        get_provider_factory("missing-provider")
    except ValueError as exc:
        assert "Unknown provider" in str(exc)
    else:
        raise AssertionError("Unknown provider should raise ValueError")


def test_new_provider_can_be_registered(monkeypatch):
    monkeypatch.setitem(PROVIDER_FACTORIES, "test-provider", lambda config: object())
    assert "test-provider" in PROVIDER_FACTORIES
