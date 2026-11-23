"""Ollama runtime adapter; all Ollama-specific HTTP details live here."""
from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from ..contracts import ModelObservation, ModelState, RuntimeProbe, RuntimeState
from ..errors import RuntimeOperationError


class OllamaRuntimeAdapter:
    runtime_id = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        controller: Any | None = None,
        request_timeout: float = 15.0,
        client_factory=httpx.AsyncClient,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Ollama endpoint must be a valid HTTP(S) URL without credentials.")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Ollama endpoint contains an invalid port.") from exc

        self.base_url = base_url.rstrip("/")
        host = parsed.hostname.lower()
        try:
            is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        self.endpoint_scope = "local" if parsed.scheme == "http" and is_loopback else "remote"
        self._trust_env = self.endpoint_scope == "remote"
        self._controller = controller
        self._request_timeout = request_timeout
        self._client_factory = client_factory

    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            async with self._client_factory(
                timeout=self._request_timeout, trust_env=self._trust_env
            ) as client:
                response = await client.get(f"{self.base_url}{path}")
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object.")
                return data
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeOperationError(
                "runtime_unreachable",
                "The configured Ollama endpoint did not return a valid response.",
                self.runtime_id,
                retryable=True,
            ) from exc

    def _probe_from_controller(self, result: dict[str, Any]) -> RuntimeProbe:
        status = result.get("status")
        mapping = {
            "ready": RuntimeState.READY,
            "not_installed": RuntimeState.NOT_INSTALLED,
            "starting_timeout": RuntimeState.FAILED,
            "error": RuntimeState.FAILED,
            "unavailable": RuntimeState.UNAVAILABLE,
        }
        error = result.get("error") or {}
        return RuntimeProbe(
            runtime_id=self.runtime_id,
            state=mapping.get(status, RuntimeState.UNKNOWN),
            endpoint_scope=result.get("endpoint_scope", self.endpoint_scope),
            already_running=bool(result.get("already_running")),
            started_by_application=bool(result.get("started_by_application")),
            process_id=result.get("process_id"),
            error_category=error.get("category"),
            message=error.get("message"),
            details={"status": status},
        )

    async def probe(self) -> RuntimeProbe:
        if self._controller is not None:
            return self._probe_from_controller(
                await self._controller.ensure_running(self.base_url, auto_start=False)
            )
        try:
            data = await self._get_json("/api/version")
            return RuntimeProbe(
                runtime_id=self.runtime_id,
                state=RuntimeState.READY,
                endpoint_scope=self.endpoint_scope,
                details={"version": data.get("version")},
            )
        except RuntimeOperationError as exc:
            return RuntimeProbe(
                runtime_id=self.runtime_id,
                state=RuntimeState.UNAVAILABLE,
                endpoint_scope=self.endpoint_scope,
                error_category=exc.category,
                message=exc.safe_message,
            )

    async def ensure_ready(self, auto_start: bool = False) -> RuntimeProbe:
        if self._controller is None:
            return await self.probe()
        result = await self._controller.ensure_running(
            self.base_url, auto_start=bool(auto_start and self.endpoint_scope == "local")
        )
        return self._probe_from_controller(result)

    async def list_installed_models(self) -> list[ModelObservation]:
        data = await self._get_json("/api/tags")
        models = data.get("models") or []
        if not isinstance(models, list):
            raise RuntimeOperationError(
                "runtime_protocol_error", "Ollama returned an invalid model catalog.", self.runtime_id
            )
        observations = []
        for item in models:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            model_id = item["name"].strip()
            if not model_id:
                continue
            observations.append(ModelObservation(
                runtime_id=self.runtime_id,
                model_id=model_id,
                state=ModelState.INSTALLED,
                installed=True,
                loaded=None,
                source="ollama_api_tags",
                metadata={
                    key: item.get(key)
                    for key in ("size", "digest", "modified_at", "details")
                    if item.get(key) is not None
                },
            ))
        return observations

    async def list_loaded_models(self) -> list[ModelObservation] | None:
        try:
            data = await self._get_json("/api/ps")
        except RuntimeOperationError:
            # A failed optional telemetry endpoint means unknown, never "not loaded".
            return None
        models = data.get("models") or []
        if not isinstance(models, list):
            return None
        return [
            ModelObservation(
                runtime_id=self.runtime_id,
                model_id=item["name"],
                state=ModelState.LOADED,
                installed=None,
                loaded=True,
                source="ollama_api_ps",
                metadata={
                    key: item.get(key)
                    for key in ("size", "size_vram", "expires_at", "details")
                    if item.get(key) is not None
                },
            )
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
        ]

    async def close(self) -> None:
        # HTTP clients are scoped to requests. The process controller intentionally
        # remains the owner of any child process and is not stopped here.
        return None
