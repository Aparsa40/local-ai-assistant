from typing import AsyncGenerator, Dict, List

import httpx

from .base import BaseLLMProvider
from .openai_compatible import OpenAICompatibleChat
from .capabilities import record_provider_quota


# Current general-purpose models selected for their published context and tool support.
RECOMMENDED_MODELS = {
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
}


class GroqProvider(BaseLLMProvider):
    """GroqCloud OpenAI-compatible chat-completions adapter."""

    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1"):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.last_quota = {"status": "unknown", "source": "awaiting first API response"}

    async def chat_stream(
        self, messages: List[Dict[str, str]], model: str, temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        client = OpenAICompatibleChat(self.api_key, self.base_url, "Groq")
        try:
            async for chunk in client.stream(messages, model, temperature):
                yield chunk
        finally:
            record_provider_quota("groq", client.last_quota)

    async def list_models(self) -> List[str]:
        if not self.api_key:
            raise RuntimeError("Groq API key is missing. Add it in Settings.")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"Groq model catalog returned HTTP {response.status_code}: {body[:1200]}")
            data = response.json()
        available = {item.get("id") for item in data.get("data", []) if isinstance(item, dict)}
        return sorted(RECOMMENDED_MODELS.intersection(available))
