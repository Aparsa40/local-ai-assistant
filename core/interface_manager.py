"""Provider-neutral service boundary for model discovery and inference.

This is the first incremental Interface Manager implementation. Provider-specific
behavior remains inside adapters registered in core.providers.registry.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from .config_manager import ConfigManager
from .providers.base import BaseLLMProvider
from .providers.capabilities import get_provider_capabilities
from .providers.registry import PROVIDER_FACTORIES


class InterfaceManagerError(Exception):
    """Safe, provider-neutral error exposed to application/API layers."""

    def __init__(self, category: str, message: str, provider_id: str):
        super().__init__(message)
        self.category = category
        self.provider_id = provider_id
        self.safe_message = message


class InterfaceManager:
    """Central boundary for provider registry, catalog, diagnostics and inference."""

    DISPLAY_NAMES = {
        "ollama": "Ollama",
        "openrouter": "OpenRouter",
        "google_ai_studio": "Google AI Studio",
        "cloudflare_workers_ai": "Cloudflare Workers AI",
        "groq": "Groq",
        "cohere": "Cohere",
    }

    def __init__(
        self,
        config_loader: Optional[Callable[[], Dict[str, Any]]] = None,
        provider_factories: Optional[Dict[str, Callable[[dict], BaseLLMProvider]]] = None,
        capabilities_getter: Optional[Callable[[str], dict]] = None,
        timeout_seconds: float = 15.0,
    ):
        self._config_loader = config_loader or ConfigManager.load_config
        self._provider_factories = provider_factories if provider_factories is not None else PROVIDER_FACTORIES
        self._capabilities_getter = capabilities_getter or get_provider_capabilities
        self._timeout_seconds = timeout_seconds

    def list_providers(self) -> List[dict]:
        """Return registered providers without exposing configuration or secrets."""
        return [
            {
                "id": provider_id,
                "name": self.DISPLAY_NAMES.get(
                    provider_id, provider_id.replace("_", " ").title()
                ),
                "capabilities_available": bool(self._capabilities_getter(provider_id)),
            }
            for provider_id in self._provider_factories
        ]

    def _create_provider(self, provider_id: str) -> BaseLLMProvider:
        factory = self._provider_factories.get(provider_id)
        if factory is None:
            raise InterfaceManagerError(
                "unknown_provider", "The requested provider is not registered.", provider_id
            )

        config = self._config_loader() or {}
        provider_config = config.get("providers_config", {}).get(provider_id, {})
        try:
            return factory(provider_config)
        except Exception as exc:
            raise InterfaceManagerError(
                "invalid_configuration",
                "The provider configuration could not be loaded.",
                provider_id,
            ) from exc

    def get_capabilities(self, provider_id: str) -> dict:
        if provider_id not in self._provider_factories:
            raise InterfaceManagerError(
                "unknown_provider", "The requested provider is not registered.", provider_id
            )
        return self._capabilities_getter(provider_id)

    async def list_models(self, provider_id: str) -> List[str]:
        """Discover exact provider model IDs with a bounded catalog request."""
        provider = self._create_provider(provider_id)
        try:
            models = await asyncio.wait_for(
                provider.list_models(), timeout=self._timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise InterfaceManagerError(
                "timeout", "The provider model catalog request timed out.", provider_id
            ) from exc
        except Exception as exc:
            raise InterfaceManagerError(
                "catalog_unavailable", "The provider model catalog could not be retrieved.", provider_id
            ) from exc

        return list(models or [])

    async def check_connection(self, provider_id: str) -> dict:
        """Probe catalog access; this does not claim inference has been verified."""
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            models = await self.list_models(provider_id)
        except InterfaceManagerError as exc:
            if exc.category == "unknown_provider":
                raise
            return {
                "provider": provider_id,
                "status": "unreachable",
                "probe": "model_catalog",
                "model_count": None,
                "checked_at": checked_at,
                "error": {"category": exc.category, "message": exc.safe_message},
            }

        return {
            "provider": provider_id,
            "status": "reachable",
            "probe": "model_catalog",
            "model_count": len(models),
            "checked_at": checked_at,
            "error": None,
        }

    async def stream_chat(
        self,
        provider_id: str,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream inference through the selected adapter without leaking raw errors."""
        provider = self._create_provider(provider_id)
        try:
            async for chunk in provider.chat_stream(
                messages=messages, model=model, temperature=temperature
            ):
                yield chunk
        except Exception as exc:
            raise InterfaceManagerError(
                "inference_failed", "The provider inference request failed.", provider_id
            ) from exc
