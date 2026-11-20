import json
from typing import AsyncGenerator, Dict, List

import httpx


class OpenAICompatibleChat:
    """Small shared SSE client for providers exposing /chat/completions."""

    def __init__(self, api_key: str, base_url: str, provider_name: str):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name

    def headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError(f"{self.provider_name} API token is missing. Add it in Settings.")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def stream(
        self, messages: List[Dict[str, str]], model: str, temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        if not model:
            raise RuntimeError(f"No {self.provider_name} model is selected.")
        payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers=self.headers(), json=payload,
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"{self.provider_name} returned HTTP {response.status_code}: {body[:1600]}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    error = event.get("error")
                    if error:
                        detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                        raise RuntimeError(f"{self.provider_name} streaming error: {detail}")
                    choices = event.get("choices") or []
                    if choices:
                        delta = (choices[0] or {}).get("delta") or {}
                        text = delta.get("content")
                        if isinstance(text, str) and text:
                            yield text
