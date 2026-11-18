import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not model:
            raise RuntimeError("No Ollama model is selected. Pull a model and select it in Settings.")
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": 1024, "num_thread": 2},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {body[:2000]}")
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    content = (data.get("message") or {}).get("content")
                    if isinstance(content, str) and content:
                        yield content
                    if data.get("error"):
                        raise RuntimeError(f"Ollama error: {data['error']}")

    async def list_models(self) -> List[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: HTTP {response.status_code}: {body[:1000]}")
            data = response.json()
        return sorted({item["name"] for item in data.get("models", []) if item.get("name")})
