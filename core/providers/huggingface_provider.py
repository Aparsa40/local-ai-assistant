import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import BaseLLMProvider


class HuggingFaceProvider(BaseLLMProvider):
    """Hugging Face Inference Providers chat-completions adapter."""

    # The model catalog's provider IDs are not always identical to routing suffixes.
    PROVIDER_SUFFIX_ALIASES = {
        "fireworks-ai": "fireworks",
        "featherless-ai": "featherless",
        "moonshot-ai": "moonshotai",
        "prime-intellect": "primeintellect",
        "zai": "z-ai",
    }
    VALID_PROVIDER_SUFFIXES = {
        "baseten", "cerebras", "cohere", "coreweave", "deepinfra",
        "digitalocean", "featherless", "fireworks", "liquid", "mistral",
        "moonshotai", "nebius", "novita", "parasail", "primeintellect",
        "reka", "tencent", "together", "z-ai",
    }

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://router.huggingface.co/v1",
    ):
        self.api_key = api_key.strip()
        normalized_url = base_url.rstrip("/")
        self.base_url = normalized_url if normalized_url.endswith("/v1") else f"{normalized_url}/v1"

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Hugging Face access token is missing. Add it in Settings.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _free_model_ids(data: Dict) -> List[str]:
        """Return exact model:provider IDs only where a live provider reports is_free."""
        model_ids = []
        for item in data.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            for provider in item.get("providers", []):
                if provider.get("status") == "live" and provider.get("is_free") is True:
                    provider_id = provider.get("provider", "")
                    suffix = HuggingFaceProvider.PROVIDER_SUFFIX_ALIASES.get(provider_id, provider_id)
                    if suffix in HuggingFaceProvider.VALID_PROVIDER_SUFFIXES:
                        model_ids.append(f"{model_id}:{suffix}")
        return sorted(set(model_ids))

    @staticmethod
    def _extract_stream_content(event: Dict) -> str:
        error = event.get("error")
        if error:
            if isinstance(error, dict):
                error = error.get("message") or json.dumps(error, ensure_ascii=False)
            raise RuntimeError(f"Hugging Face streaming error: {error}")
        choices = event.get("choices") or []
        if not choices:
            return ""
        delta = (choices[0] or {}).get("delta") or {}
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not model:
            raise RuntimeError("No Hugging Face model is selected. Refresh the free model list in Settings.")
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Hugging Face Inference Providers returned HTTP {response.status_code}: {body[:2000]}"
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
                    content = self._extract_stream_content(event)
                    if content:
                        yield content

    async def list_models(self) -> List[str]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Hugging Face model catalog returned HTTP {response.status_code}: {body[:1200]}"
                )
            data = response.json()
        model_ids = self._free_model_ids(data)
        if not model_ids:
            raise RuntimeError(
                "Hugging Face currently reports no live free chat providers for the available models. "
                "Check your Inference Providers access and refresh the list later."
            )
        return model_ids
