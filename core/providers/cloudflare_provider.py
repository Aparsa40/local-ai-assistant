import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import BaseLLMProvider


# Models confirmed as accessible on the Workers Free plan at implementation time.
# Keep this allowlist conservative; Cloudflare may change plan eligibility.
FREE_CHAT_MODELS = {
    "@cf/zai-org/glm-4.7-flash",
    "@cf/google/gemma-4-26b-a4b-it",
}


class CloudflareWorkersAIProvider(BaseLLMProvider):
    """Cloudflare Workers AI REST adapter (account-scoped inference endpoint)."""

    def __init__(self, api_key: str, account_id: str, base_url: str = "https://api.cloudflare.com/client/v4"):
        self.api_key = api_key.strip()
        self.account_id = account_id.strip()
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Cloudflare API token is missing. Add it in Settings.")
        if not self.account_id:
            raise RuntimeError("Cloudflare Account ID is missing. Add it in Settings.")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _extract_text(event: Dict) -> str:
        if event.get("response"):
            return str(event["response"])
        if event.get("result", {}).get("response"):
            return str(event["result"]["response"])
        return ""

    async def chat_stream(
        self, messages: List[Dict[str, str]], model: str, temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        if not model:
            raise RuntimeError("No Cloudflare Workers AI model is selected.")
        url = f"{self.base_url}/accounts/{self.account_id}/ai/run/{model}"
        payload = {"messages": messages, "stream": True, "temperature": temperature}
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Cloudflare Workers AI returned HTTP {response.status_code}: {body[:1600]}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        raise RuntimeError(f"Cloudflare Workers AI stream error: {event['error']}")
                    text = self._extract_text(event)
                    if text:
                        yield text

    async def list_models(self) -> List[str]:
        headers = self._headers()
        url = f"{self.base_url}/accounts/{self.account_id}/ai/models/search"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers, params={"task": "Text Generation", "per_page": 100})
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"Cloudflare model catalog returned HTTP {response.status_code}: {body[:1200]}")
            data = response.json()
        available = {
            item.get("name") or item.get("model")
            for item in data.get("result", [])
            if isinstance(item, dict)
        }
        return sorted(FREE_CHAT_MODELS.intersection(available))
