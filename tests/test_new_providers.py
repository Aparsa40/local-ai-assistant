import pytest

from core.providers.cloudflare_provider import CloudflareWorkersAIProvider
from core.providers.cohere_provider import CohereProvider
from core.providers.groq_provider import GroqProvider
from core.providers.capabilities import get_provider_capabilities


def test_cloudflare_stream_response_extraction():
    assert CloudflareWorkersAIProvider._extract_text({"response": "سلام"}) == "سلام"
    assert CloudflareWorkersAIProvider._extract_text({"result": {"response": "Hello"}}) == "Hello"


def test_cloudflare_requires_account_and_token():
    provider = CloudflareWorkersAIProvider(api_key="", account_id="")
    with pytest.raises(RuntimeError, match="token is missing"):
        provider._headers()
    provider = CloudflareWorkersAIProvider(api_key="token", account_id="")
    with pytest.raises(RuntimeError, match="Account ID is missing"):
        provider._headers()


def test_cohere_content_delta_extraction():
    event = {
        "type": "content-delta",
        "delta": {"message": {"content": {"text": "سلام"}}},
    }
    assert CohereProvider._extract_text(event) == "سلام"


def test_cohere_ignores_non_text_events():
    assert CohereProvider._extract_text({"type": "message-start"}) == ""


def test_groq_recommended_models_are_current_and_task_suitable():
    from core.providers.groq_provider import RECOMMENDED_MODELS
    assert "openai/gpt-oss-20b" in RECOMMENDED_MODELS
    assert "openai/gpt-oss-120b" in RECOMMENDED_MODELS
    assert "qwen/qwen3.8-27b" in RECOMMENDED_MODELS


def test_provider_capabilities_include_quota_and_model_metadata():
    data = get_provider_capabilities("cloudflare_workers_ai")
    assert data["quota"]["allowance"] == "10,000 Neurons/day"
    assert data["models"]["@cf/zai-org/glm-4.7-flash"]["context_window"] == 131072
    assert data["models"]["@cf/zai-org/glm-4.7-flash"]["tool_calling"] is True


def test_capability_catalog_filters_to_live_discovered_models():
    data = get_provider_capabilities("groq", ["openai/gpt-oss-20b"])
    assert list(data["models"]) == ["openai/gpt-oss-20b"]
