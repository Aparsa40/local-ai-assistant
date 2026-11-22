import importlib
import json
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List

from .base import BaseLLMProvider


class OpenRouterProvider(BaseLLMProvider):
    """OpenAI-compatible OpenRouter adapter."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key.strip()
        normalized_url = base_url.rstrip("/")
        if normalized_url.endswith("/api/v1"):
            self.base_url = normalized_url
        else:
            self.base_url = f"{normalized_url}/api/v1"

    def _client_module(self):
        try:
            return importlib.import_module("httpx")
        except ImportError as exc:
            raise RuntimeError(
                "OpenRouter requires httpx. Install dependencies with: pip install -r requirements.txt"
            ) from exc

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not self.api_key:
            raise RuntimeError("OpenRouter API key is missing. Add it in Settings.")
        httpx = self._client_module()
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Local AI Assistant",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"OpenRouter API returned HTTP {response.status_code}: {body[:2000]}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload_line = line[5:].strip()
                    if payload_line == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_line)
                    except json.JSONDecodeError:
                        continue
                    content = self._extract_stream_content(data)
                    if content:
                        yield content

    @staticmethod
    def _extract_stream_content(data: Dict) -> str:
        """Extract a text delta or raise when OpenRouter reports an in-stream error."""
        error = data.get("error")
        if error:
            if isinstance(error, dict):
                message = error.get("message") or json.dumps(error, ensure_ascii=False)
                code = error.get("code")
                detail = f" (code: {code})" if code is not None else ""
            else:
                message = str(error)
                detail = ""
            raise RuntimeError(f"OpenRouter streaming error: {message}{detail}")

        choices = data.get("choices") or []
        if not choices:
            return ""

        choice = choices[0] or {}
        if choice.get("finish_reason") == "error":
            error_detail = choice.get("error") or data.get("message") or "The provider ended the stream with an error."
            if isinstance(error_detail, dict):
                error_detail = error_detail.get("message") or json.dumps(error_detail, ensure_ascii=False)
            raise RuntimeError(f"OpenRouter streaming error: {error_detail}")

        delta = choice.get("delta") or {}
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    async def get_quota_status(self) -> Dict:
        """Read usage/remaining spend for the current API key when OpenRouter exposes it."""
        if not self.api_key:
            return {"status": "credentials_missing", "source": "GET /api/v1/key"}
        httpx = self._client_module()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/key",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if response.is_error:
                raise RuntimeError(f"OpenRouter key usage endpoint returned HTTP {response.status_code}")
            payload = response.json().get("data", {})
        allowed = (
            "is_free_tier", "usage", "usage_daily", "usage_weekly",
            "usage_monthly", "limit", "limit_remaining", "limit_reset", "expires_at"
        )
        return {
            "status": "observed",
            "source": "GET /api/v1/key",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "data": {key: payload[key] for key in allowed if key in payload},
        }

    async def list_models(self) -> List[str]:
        """Return the currently available free chat models plus the free router."""
        httpx = self._client_module()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{self.base_url}/models", headers=headers)
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"OpenRouter model catalog returned HTTP {response.status_code}: {body[:1000]}"
                )
            data = response.json()
        model_ids = []
        for item in data.get("data", []):
            model_id = item.get("id")
            pricing = item.get("pricing") or {}
            try:
                is_free = float(pricing.get("prompt", -1)) == 0 and float(pricing.get("completion", -1)) == 0
            except (TypeError, ValueError):
                is_free = False
            if model_id and (model_id.endswith(":free") or is_free):
                model_ids.append(model_id)
        return ["openrouter/free", *sorted(set(model_ids))]
