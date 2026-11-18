from abc import abstractmethod
import importlib
import json
from typing import List, Dict, AsyncGenerator
from .base import BaseLLMProvider

class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        try:
            httpx = importlib.import_module("httpx")
        except ImportError as exc:
            raise RuntimeError(
                "The OpenRouter provider requires the 'httpx' package. Install it with 'pip install httpx'."
            ) from exc

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]

    async def list_models(self) -> List[str]:
        return ["openai/gpt-4o-mini", "anthropic/claude-3-haiku", "google/gemini-flash-1.5"]