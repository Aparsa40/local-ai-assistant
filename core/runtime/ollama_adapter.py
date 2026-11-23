"""Ollama control-plane adapter. Chat inference remains in OllamaProvider/InterfaceManager."""
from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from .contracts import RuntimeAdapter, RuntimeResult


class OllamaRuntimeAdapter(RuntimeAdapter):
    runtime_id = "ollama"
    capabilities = frozenset({
        "process_start", "model_inventory", "model_inspection", "model_load", "model_unload",
    })

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        controller=None,
        request_timeout: float = 20.0,
        config_loader=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.controller = controller
        self.request_timeout = request_timeout
        self.config_loader = config_loader
        self._refresh_config()

    def _refresh_config(self) -> None:
        if self.config_loader is not None:
            config = self.config_loader() or {}
            provider_config = (config.get("providers_config") or {}).get("ollama", {})
            self.base_url = str(provider_config.get("base_url") or self.base_url).rstrip("/")
        parsed = urlparse(self.base_url)
        host = parsed.hostname or ""
        try:
            is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        self._trust_env = not (parsed.scheme == "http" and is_loopback)

    async def _request(self, method: str, path: str, **kwargs):
        self._refresh_config()
        async with httpx.AsyncClient(
            timeout=self.request_timeout,
            trust_env=self._trust_env,
        ) as client:
            response = await client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}

    @staticmethod
    def _failure(
        category: str,
        message: str,
        model_id: str | None = None,
        retryable: bool = False,
    ) -> RuntimeResult:
        state = "not_installed" if category == "ollama_not_installed" else (
            "unavailable" if model_id is None else "failed"
        )
        return RuntimeResult(
            False,
            "ollama",
            state,
            model_id,
            error={"category": category, "message": message, "retryable": retryable},
        )

    async def ensure_available(self, auto_start: bool = True) -> RuntimeResult:
        self._refresh_config()
        if self.controller is not None:
            startup = await self.controller.ensure_running(self.base_url, auto_start=auto_start)
            if startup.get("status") != "ready":
                error = startup.get("error") or {}
                return self._failure(
                    error.get("category", "runtime_unavailable"),
                    error.get("message", "Ollama runtime is unavailable."),
                    retryable=True,
                )
            return RuntimeResult(
                True,
                self.runtime_id,
                "ready",
                data={
                    "endpoint_scope": startup.get("endpoint_scope"),
                    "already_running": startup.get("already_running"),
                    "started_by_application": startup.get("started_by_application"),
                    "process_id": startup.get("process_id"),
                },
            )
        try:
            data = await self._request("GET", "/api/version")
            return RuntimeResult(
                True,
                self.runtime_id,
                "ready",
                data={
                    "version": data.get("version"),
                    "endpoint_scope": "local" if not self._trust_env else "remote",
                },
            )
        except (httpx.HTTPError, ValueError):
            return self._failure(
                "runtime_unavailable",
                "Ollama did not respond to its version endpoint.",
                retryable=True,
            )

    async def list_models(self) -> RuntimeResult:
        try:
            tags = await self._request("GET", "/api/tags")
            try:
                running = await self._request("GET", "/api/ps")
                loaded_ids = {
                    item.get("name")
                    for item in running.get("models", [])
                    if item.get("name")
                }
                loaded_known = True
            except (httpx.HTTPError, ValueError):
                loaded_ids, loaded_known = set(), False
            models = [
                {
                    "model_id": item["name"],
                    "installed": True,
                    "loaded": item["name"] in loaded_ids if loaded_known else None,
                    "size": item.get("size"),
                    "digest": item.get("digest"),
                    "modified_at": item.get("modified_at"),
                    "details": item.get("details") or {},
                }
                for item in tags.get("models", [])
                if item.get("name")
            ]
            return RuntimeResult(
                True,
                self.runtime_id,
                "ready",
                data={
                    "models": models,
                    "loaded_state_source": "ollama_api_ps" if loaded_known else None,
                },
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return self._failure(
                "model_inventory_unavailable",
                "Ollama's installed model inventory could not be read.",
                retryable=True,
            )

    async def inspect_model(self, model_id: str) -> RuntimeResult:
        inventory = await self.list_models()
        if not inventory.ok:
            return inventory
        model = next(
            (item for item in inventory.data["models"] if item["model_id"] == model_id),
            None,
        )
        if model is None:
            return self._failure(
                "model_not_found",
                "The model was not found in the installed Ollama inventory.",
                model_id,
            )
        state = (
            "loaded" if model.get("loaded") is True
            else "installed" if model.get("loaded") is False
            else "unknown"
        )
        return RuntimeResult(True, self.runtime_id, state, model_id, data=model)

    async def load_model(
        self,
        model_id: str,
        options: dict[str, Any] | None = None,
    ) -> RuntimeResult:
        options = options or {}
        keep_alive = options.get("keep_alive", "5m")
        try:
            await self._request(
                "POST",
                "/api/generate",
                json={
                    "model": model_id,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": keep_alive,
                },
            )
            inspected = await self.inspect_model(model_id)
            if not inspected.ok:
                return self._failure(
                    "load_verification_failed",
                    "Ollama accepted the load request but the resulting model state could not be verified.",
                    model_id,
                    retryable=True,
                )
            return RuntimeResult(
                True,
                self.runtime_id,
                inspected.state,
                model_id,
                data={"operation": "load", "keep_alive": keep_alive, **inspected.data},
            )
        except (httpx.HTTPError, ValueError):
            return self._failure(
                "load_failed",
                "Ollama could not load the requested model.",
                model_id,
                retryable=True,
            )

    async def shutdown_owned_process(self) -> RuntimeResult:
        if self.controller is None:
            return RuntimeResult(
                True,
                self.runtime_id,
                "ready",
                data={"process_stopped": False, "reason": "no_process_controller"},
            )
        result = await self.controller.shutdown_owned_process()
        if result.get("status") == "failed":
            error = result.get("error") or {}
            return self._failure(
                error.get("category", "shutdown_failed"),
                error.get("message", "The application-owned Ollama process could not be stopped."),
                retryable=True,
            )
        return RuntimeResult(
            True,
            self.runtime_id,
            "stopped",
            data={
                "process_stopped": bool(result.get("process_stopped")),
                "reason": result.get("reason"),
            },
        )

    async def unload_model(self, model_id: str) -> RuntimeResult:
        before = await self.inspect_model(model_id)
        if not before.ok:
            return before
        if before.state == "installed":
            return RuntimeResult(
                True,
                self.runtime_id,
                "installed",
                model_id,
                data={"operation": "unload", "already_unloaded": True, "loaded": False},
            )
        try:
            await self._request(
                "POST",
                "/api/generate",
                json={"model": model_id, "prompt": "", "stream": False, "keep_alive": 0},
            )
            inspected = await self.inspect_model(model_id)
            if not inspected.ok:
                return self._failure(
                    "unload_verification_failed",
                    "Ollama accepted the unload request but the resulting model state could not be verified.",
                    model_id,
                    retryable=True,
                )
            if inspected.state == "loaded":
                return self._failure(
                    "unload_failed",
                    "Ollama still reports the model as loaded after the unload request.",
                    model_id,
                    retryable=True,
                )
            return RuntimeResult(
                True,
                self.runtime_id,
                inspected.state,
                model_id,
                data={"operation": "unload", "loaded": False if inspected.state == "installed" else None},
            )
        except (httpx.HTTPError, ValueError):
            return self._failure(
                "unload_failed",
                "Ollama could not unload the requested model.",
                model_id,
                retryable=True,
            )
