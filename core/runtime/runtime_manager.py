"""Provider-neutral orchestration for local runtime adapters."""
from __future__ import annotations

import asyncio
from typing import Mapping

from .contracts import (
    ModelObservation,
    RuntimeAdapter,
    RuntimeProbe,
    normalize_model_observations,
)
from .errors import RuntimeNotRegisteredError, RuntimeOperationError
from .registry import RuntimeRegistry


class RuntimeManager:
    def __init__(
        self,
        adapters: Mapping[str, RuntimeAdapter] | None = None,
        registry: RuntimeRegistry | None = None,
        operation_timeout: float = 30.0,
        max_concurrent_operations: int = 2,
    ) -> None:
        if operation_timeout <= 0 or max_concurrent_operations < 1:
            raise ValueError("Runtime timeout and concurrency limit must be positive.")
        self._adapters = dict(adapters or {})
        self.registry = registry or RuntimeRegistry()
        self.operation_timeout = operation_timeout
        self._semaphore = asyncio.Semaphore(max_concurrent_operations)

        for runtime_id, adapter in self._adapters.items():
            if runtime_id != adapter.runtime_id:
                raise ValueError("Runtime adapter key must match adapter.runtime_id.")

    def register(self, adapter: RuntimeAdapter) -> None:
        self._adapters[adapter.runtime_id] = adapter

    def _adapter(self, runtime_id: str) -> RuntimeAdapter:
        try:
            return self._adapters[runtime_id]
        except KeyError as exc:
            raise RuntimeNotRegisteredError(runtime_id) from exc

    async def _run(self, runtime_id: str, operation: str, awaitable):
        try:
            async with self._semaphore:
                return await asyncio.wait_for(awaitable, timeout=self.operation_timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeOperationError(
                "runtime_request_timeout",
                f"Runtime operation '{operation}' timed out.",
                runtime_id,
                retryable=True,
            ) from exc
        except RuntimeOperationError:
            raise
        except Exception as exc:
            raise RuntimeOperationError(
                "runtime_protocol_error",
                f"Runtime operation '{operation}' failed.",
                runtime_id,
                retryable=False,
            ) from exc

    async def probe(self, runtime_id: str) -> RuntimeProbe:
        adapter = self._adapter(runtime_id)
        result = await self._run(runtime_id, "probe", adapter.probe())
        self.registry.record_runtime(result)
        return result

    async def ensure_ready(self, runtime_id: str, auto_start: bool = False) -> RuntimeProbe:
        adapter = self._adapter(runtime_id)
        result = await self._run(
            runtime_id, "ensure_ready", adapter.ensure_ready(auto_start=auto_start)
        )
        self.registry.record_runtime(result)
        return result

    async def list_installed_models(self, runtime_id: str) -> list[ModelObservation]:
        adapter = self._adapter(runtime_id)
        result = await self._run(
            runtime_id, "list_installed_models", adapter.list_installed_models()
        )
        normalized = normalize_model_observations(runtime_id, result)
        self.registry.record_models(normalized)
        return normalized

    async def list_loaded_models(self, runtime_id: str) -> list[ModelObservation] | None:
        adapter = self._adapter(runtime_id)
        result = await self._run(
            runtime_id, "list_loaded_models", adapter.list_loaded_models()
        )
        if result is None:
            return None
        normalized = normalize_model_observations(runtime_id, result)
        self.registry.record_models(normalized)
        return normalized

    async def close(self) -> None:
        await asyncio.gather(
            *(adapter.close() for adapter in self._adapters.values()),
            return_exceptions=True,
        )
