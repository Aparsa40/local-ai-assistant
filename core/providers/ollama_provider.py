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


    async def list_model_metadata(self, model_ids: List[str]) -> dict:
        """Enrich one live tag snapshot with bounded per-model /api/show metadata."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            tags_response = await client.get(f"{self.base_url}/api/tags")
            tags_response.raise_for_status()
            tags = {
                item.get("name"): item
                for item in (tags_response.json().get("models") or [])
                if item.get("name") in set(model_ids)
            }

            semaphore = __import__("asyncio").Semaphore(3)

            async def collect(model_id):
                tag = tags.get(model_id, {})
                base = {
                    "size": tag.get("size"),
                    "digest": tag.get("digest"),
                    "modified_at": tag.get("modified_at"),
                    "details": tag.get("details") or {},
                    "metadata_source": "ollama_api_tags",
                }
                async with semaphore:
                    try:
                        response = await client.post(
                            f"{self.base_url}/api/show",
                            json={"model": model_id, "verbose": False},
                        )
                        response.raise_for_status()
                        data = response.json()
                        details = data.get("details") or base["details"]
                        model_info = data.get("model_info") or {}
                        useful_info = {
                            key: value for key, value in model_info.items()
                            if any(marker in key.lower() for marker in (
                                "context_length", "embedding_length", "block_count",
                                "head_count", "vision", "projector",
                            ))
                        }
                        base.update({
                            "details": {
                                "format": details.get("format"),
                                "family": details.get("family"),
                                "families": details.get("families"),
                                "parameter_size": details.get("parameter_size"),
                                "quantization_level": details.get("quantization_level"),
                            },
                            "capabilities": data.get("capabilities") or [],
                            "model_info": useful_info,
                            "context_length": next(
                                (value for key, value in useful_info.items() if key.endswith("context_length")),
                                None,
                            ),
                            "template_available": bool(data.get("template")),
                            "metadata_source": "ollama_api_show",
                        })
                        return model_id, base, None
                    except Exception:
                        return model_id, base, {"model_id": model_id, "category": "metadata_unavailable"}

            import asyncio
            results = await asyncio.gather(*(collect(model_id) for model_id in model_ids))
        return {
            "models": {model_id: metadata for model_id, metadata, _error in results},
            "errors": [error for _model_id, _metadata, error in results if error],
        }
