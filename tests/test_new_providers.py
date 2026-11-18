import pytest

from core.providers.google_ai_studio_provider import FREE_TIER_MODEL_IDS, GoogleAIStudioProvider
from core.providers.huggingface_provider import HuggingFaceProvider


def test_gemini_interactions_text_delta_is_extracted():
    event = {
        "event_type": "step.delta",
        "delta": {"type": "text", "text": "سلام"},
    }
    assert GoogleAIStudioProvider._extract_stream_content(event) == "سلام"


def test_gemini_non_text_interactions_events_are_ignored():
    assert GoogleAIStudioProvider._extract_stream_content(
        {"event_type": "step.delta", "delta": {"type": "thought", "signature": "abc"}}
    ) == ""


def test_gemini_input_preserves_system_and_chat_roles():
    messages = [
        {"role": "system", "content": "Be concise"},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    prompt = GoogleAIStudioProvider._build_input(messages)
    assert GoogleAIStudioProvider._system_instruction(messages) == "Be concise"
    assert "User: Hi" in prompt
    assert "Assistant: Hello" in prompt
    assert "Be concise" not in prompt


def test_huggingface_catalog_returns_only_live_free_provider_model_ids():
    catalog = {
        "data": [
            {
                "id": "Qwen/Qwen3-4B",
                "providers": [
                    {"provider": "novita", "status": "live", "is_free": True},
                    {"provider": "together", "status": "live", "is_free": False},
                ],
            },
            {
                "id": "meta-llama/Llama-3",
                "providers": [{"provider": "replicate", "status": "error", "is_free": True}],
            },
        ]
    }
    assert HuggingFaceProvider._free_model_ids(catalog) == ["Qwen/Qwen3-4B:novita"]


def test_huggingface_stream_delta_is_extracted():
    event = {"choices": [{"delta": {"content": "Hello"}}]}
    assert HuggingFaceProvider._extract_stream_content(event) == "Hello"


def test_huggingface_stream_error_is_reported():
    with pytest.raises(RuntimeError, match="quota exceeded"):
        HuggingFaceProvider._extract_stream_content({"error": {"message": "quota exceeded"}})



def test_gemini_free_tier_catalog_is_explicit_and_known():
    assert "gemini-3.8-flash" in FREE_TIER_MODEL_IDS
    assert "gemini-3.1-flash-lite" in FREE_TIER_MODEL_IDS
    assert "gemini-2.5-flash" in FREE_TIER_MODEL_IDS
    assert "gemini-2.5-flash-lite" in FREE_TIER_MODEL_IDS



def test_huggingface_catalog_normalizes_provider_ids_to_routing_suffixes():
    catalog = {
        "data": [
            {
                "id": "Qwen/Qwen3-4B",
                "providers": [
                    {"provider": "fireworks-ai", "status": "live", "is_free": True},
                    {"provider": "featherless-ai", "status": "live", "is_free": True},
                ],
            }
        ]
    }
    assert HuggingFaceProvider._free_model_ids(catalog) == [
        "Qwen/Qwen3-4B:featherless",
        "Qwen/Qwen3-4B:fireworks",
    ]
