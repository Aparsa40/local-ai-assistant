import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import BaseLLMProvider


# Kept aligned with Google's published Gemini Developer API free-tier pricing.
FREE_TIER_MODEL_IDS = {
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
}


class GoogleAIStudioProvider(BaseLLMProvider):
    """Google Gemini provider using the current Interactions streaming API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ):
        self.api_key = api_key.strip()
        normalized_url = base_url.rstrip("/")
        self.base_url = normalized_url if normalized_url.endswith("/v1beta") else f"{normalized_url}/v1beta"

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Google AI Studio API key is missing. Add it in Settings.")
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _system_instruction(messages: List[Dict[str, str]]) -> str:
        return "\n\n".join(
            item.get("content", "") for item in messages if item.get("role") == "system"
        )

    @staticmethod
    def _build_input(messages: List[Dict[str, str]]) -> str:
        """Preserve user/assistant turns in a stateless Interactions input."""
        labels = {"user": "User", "assistant": "Assistant"}
        return "\n\n".join(
            f"{labels.get(item.get('role', 'user'), item.get('role', 'User'))}: {item.get('content', '')}"
            for item in messages
            if item.get("role") != "system"
        )

    @staticmethod
    def _extract_stream_content(event: Dict) -> str:
        if event.get("event_type") == "error" or event.get("error"):
            error = event.get("error") or event.get("message") or "Gemini streaming request failed."
            if isinstance(error, dict):
                error = error.get("message") or json.dumps(error, ensure_ascii=False)
            raise RuntimeError(f"Google AI Studio error: {error}")
        delta = event.get("delta") or {}
        if event.get("event_type") == "step.delta" and delta.get("type") == "text":
            text = delta.get("text")
            return text if isinstance(text, str) else ""
        return ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not model:
            raise RuntimeError("No Gemini model is selected. Refresh the model list in Settings.")
        payload = {
            "model": model,
            "input": self._build_input(messages),
            "system_instruction": self._system_instruction(messages),
            "stream": True,
            "store": False,
            "generation_config": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/interactions?alt=sse",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Google AI Studio returned HTTP {response.status_code}: {body[:2000]}"
                    )
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
                    content = self._extract_stream_content(event)
                    if content:
                        yield content

    async def list_models(self) -> List[str]:
        headers = self._headers()
        models = []
        page_token = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                params = {"pageSize": 1000}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(f"{self.base_url}/models", headers=headers, params=params)
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Google AI Studio model catalog returned HTTP {response.status_code}: {body[:1200]}"
                    )
                data = response.json()
                for item in data.get("models", []):
                    name = item.get("name", "")
                    model_id = name.removeprefix("models/")
                    lowered = model_id.lower()
                    if model_id not in FREE_TIER_MODEL_IDS:
                        continue
                    if any(term in lowered for term in ("embedding", "imagen", "veo", "tts", "transcribe", "robotics")):
                        continue
                    models.append(model_id)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return sorted(set(models))
