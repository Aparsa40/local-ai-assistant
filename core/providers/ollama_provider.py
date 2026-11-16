import httpx  # type: ignore[import-not-found]
import json
from typing import List, Dict, AsyncGenerator
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
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": 1024,      # کاهش مصرف رم از ۴۰۹۶ به ۱۰۲۴ توکن
                "num_thread": 2       # جلوگیری از درگیر شدن ۱۰۰ درصدی CPU و قفل شدن ویندوز
            }
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]

    async def list_models(self) -> List[str]:
        url = f"{self.base_url}/api/tags"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
            return []