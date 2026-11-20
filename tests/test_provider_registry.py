from core.providers.registry import PROVIDER_FACTORIES, get_provider_factory, register_provider
from core.providers.ollama_provider import OllamaProvider
from core.providers.openrouter_provider import OpenRouterProvider


def test_builtin_providers_are_registered():
    assert {
        "ollama", "openrouter", "google_ai_studio",
        "cloudflare_workers_ai", "groq", "cohere",
    }.issubset(PROVIDER_FACTORIES)
    assert "huggingface" not in PROVIDER_FACTORIES


def test_ollama_factory_uses_configured_base_url():
    provider = get_provider_factory("ollama")({"base_url": "http://127.0.0.1:11434"})
    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://127.0.0.1:11434"


def test_openrouter_factory_normalizes_api_url():
    provider = get_provider_factory("openrouter")({"base_url": "https://openrouter.ai", "api_key": "test"})
    assert isinstance(provider, OpenRouterProvider)
    assert provider.base_url == "https://openrouter.ai/api/v1"


def test_cloud_provider_factories_use_expected_configuration():
    from core.providers.cloudflare_provider import CloudflareWorkersAIProvider
    from core.providers.groq_provider import GroqProvider
    from core.providers.cohere_provider import CohereProvider

    cloudflare = get_provider_factory("cloudflare_workers_ai")({"api_key": "token", "account_id": "acct"})
    groq = get_provider_factory("groq")({"api_key": "token"})
    cohere = get_provider_factory("cohere")({"api_key": "token"})
    assert isinstance(cloudflare, CloudflareWorkersAIProvider)
    assert cloudflare.account_id == "acct"
    assert isinstance(groq, GroqProvider)
    assert groq.base_url == "https://api.groq.com/openai/v1"
    assert isinstance(cohere, CohereProvider)
    assert cohere.base_url == "https://api.cohere.com"


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
