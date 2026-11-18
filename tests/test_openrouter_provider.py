import pytest

from core.providers.openrouter_provider import OpenRouterProvider


def test_stream_delta_content_is_extracted():
    event = {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
    assert OpenRouterProvider._extract_stream_content(event) == "Hello"


def test_stream_error_event_raises_runtime_error():
    event = {"error": {"message": "Provider overloaded", "code": 429}}
    with pytest.raises(RuntimeError, match="Provider overloaded"):
        OpenRouterProvider._extract_stream_content(event)


def test_stream_error_finish_reason_raises_runtime_error():
    event = {
        "choices": [
            {
                "delta": {},
                "finish_reason": "error",
                "error": {"message": "Upstream generation failed"},
            }
        ]
    }
    with pytest.raises(RuntimeError, match="Upstream generation failed"):
        OpenRouterProvider._extract_stream_content(event)


def test_stream_non_text_or_empty_events_are_ignored():
    assert OpenRouterProvider._extract_stream_content({"choices": []}) == ""
    assert OpenRouterProvider._extract_stream_content(
        {"choices": [{"delta": {"content": None}, "finish_reason": None}]}
    ) == ""
