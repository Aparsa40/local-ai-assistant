import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import BaseLLMProvider


class CohereProvider(BaseLLMProvider):
    """Cohere Chat v2 adapter with SSE streaming and live chat-model discovery."""

    def __init__(self, api_key: str, base_url: str = "https://api.cohere.com"):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Cohere API key is missing. Add it in Settings.")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _extract_text(event: Dict) -> str:
        if event.get("type") == "content-delta":
            delta = event.get("delta") or {}
            message = delta.get("message") or {}
            content = message.get("content") or {}
            text = content.get("text")
            return text if isinstance(text, str) else ""
        if event.get("type") == "error":
            raise RuntimeError(f"Cohere streaming error: {event.get('message') or event.get('error')}")
        return ""

    async def chat_stream(
        self, messages: List[Dict[str, str]], model: str, temperature: float = 0.3
    ) -> AsyncGenerator[str, None]:
        if not model:
            raise RuntimeError("No Cohere model is selected.")
        payload = {"model": model, "messages": messages, "stream": True, "temperature": temperature}
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v2/chat", headers=self._headers(), json=payload
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Cohere returned HTTP {response.status_code}: {body[:1600]}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    text = self._extract_text(event)
                    if text:
                        yield text

    async def list_models(self) -> List[str]:
        headers = self._headers()
        models = []
        page_token = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                params = {"endpoint": "chat", "page_size": 1000}
                if page_token:
                    params["page_token"] = page_token
                response = await client.get(f"{self.base_url}/v1/models", headers=headers, params=params)
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Cohere model catalog returned HTTP {response.status_code}: {body[:1200]}")
                data = response.json()
                models.extend(
                    item["name"] for item in data.get("models", [])
                    if item.get("name") and not item.get("is_deprecated")
                    and "chat" in item.get("endpoints", [])
                )
                page_token = data.get("next_page_token")
                if not page_token:
                    break
        return sorted(set(models))
