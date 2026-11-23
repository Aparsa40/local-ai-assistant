"""Provider-neutral lifecycle orchestration for local model runtimes."""
from __future__ import annotations

import asyncio

from .contracts import RuntimeAdapter, RuntimeResult
from .resource_manager import ResourceManager
from .model_lifecycle import ModelLifecycle


class RuntimeManager:
    def __init__(self, adapters: list[RuntimeAdapter] | None = None, repository=None, resource_manager=None):
        self._adapters = {adapter.runtime_id: adapter for adapter in (adapters or [])}
        self.repository = repository
        self.resources = resource_manager or ResourceManager()
        self.lifecycle = ModelLifecycle()
        self._runtime_locks: dict[str, asyncio.Lock] = {}
        self._model_locks: dict[tuple[str, str], asyncio.Lock] = {}

    def register(self, adapter: RuntimeAdapter) -> None:
        if not adapter.runtime_id or adapter.runtime_id in self._adapters:
            raise ValueError("Runtime adapter ID must be unique and non-empty.")
        self._adapters[adapter.runtime_id] = adapter

    def get_adapter(self, runtime_id: str) -> RuntimeAdapter:
        try:
            return self._adapters[runtime_id]
        except KeyError as exc:
            raise KeyError(f"Runtime is not registered: {runtime_id}") from exc

    def _runtime_lock(self, runtime_id: str) -> asyncio.Lock:
        return self._runtime_locks.setdefault(runtime_id, asyncio.Lock())

    def _model_lock(self, runtime_id: str, model_id: str) -> asyncio.Lock:
        return self._model_locks.setdefault((runtime_id, model_id), asyncio.Lock())

    def _persist(self, result: RuntimeResult, event_type: str) -> None:
        if self.repository is not None:
            self.repository.record(result, event_type)

    async def ensure_runtime(self, runtime_id: str, auto_start: bool = True) -> dict:
        adapter = self.get_adapter(runtime_id)
        async with self._runtime_lock(runtime_id):
            result = await adapter.ensure_available(auto_start=auto_start)
            self._persist(result, "runtime_probe")
            return result.to_dict()

    async def list_models(self, runtime_id: str, refresh: bool = True) -> dict:
        adapter = self.get_adapter(runtime_id)
        if refresh:
            ready = await self.ensure_runtime(runtime_id, auto_start=False)
            if not ready["ok"]:
                return ready
        result = await adapter.list_models()
        self._persist(result, "model_inventory")
        return result.to_dict()

    async def inspect_model(self, runtime_id: str, model_id: str) -> dict:
        result = await self.get_adapter(runtime_id).inspect_model(model_id)
        self._persist(result, "model_inspection")
        return result.to_dict()

    async def load_model(
        self, runtime_id: str, model_id: str, options: dict | None = None, auto_start: bool = True
    ) -> dict:
        adapter = self.get_adapter(runtime_id)
        async with self._model_lock(runtime_id, model_id):
            ready = await self.ensure_runtime(runtime_id, auto_start=auto_start)
            if not ready["ok"]:
                return ready
            inventory = await adapter.list_models()
            if not inventory.ok:
                self._persist(inventory, "model_inventory_failed")
                return inventory.to_dict()
            models = inventory.data.get("models", [])
            target = next((item for item in models if item.get("model_id") == model_id), None)
            if target is None:
                result = RuntimeResult(
                    False, runtime_id, "failed", model_id,
                    error={"category": "model_not_installed", "message": "The requested model is not installed in this runtime.", "retryable": False},
                )
                self._persist(result, "load_failed")
                return result.to_dict()
            if target.get("loaded") is True:
                result = RuntimeResult(True, runtime_id, "loaded", model_id, data={**target, "already_loaded": True})
                self._persist(result, "model_load")
                return result.to_dict()
            currently_loaded = sum(1 for item in models if item.get("loaded") is True)
            allowed, reason = self.resources.can_load(currently_loaded)
            if not allowed:
                result = RuntimeResult(
                    False, runtime_id, "installed", model_id,
                    error={"category": "resource_limit_exceeded", "message": reason, "retryable": True},
                )
                self._persist(result, "load_rejected")
                return result.to_dict()
            self.lifecycle.transition("installed", "loading")
            result = await adapter.load_model(model_id, options or {})
            self.lifecycle.transition("loading", result.state if result.ok else "failed")
            self._persist(result, "model_load" if result.ok else "load_failed")
            return result.to_dict()

    async def unload_model(self, runtime_id: str, model_id: str) -> dict:
        adapter = self.get_adapter(runtime_id)
        async with self._model_lock(runtime_id, model_id):
            before = await adapter.inspect_model(model_id)
            if not before.ok:
                self._persist(before, "unload_failed")
                return before.to_dict()
            if before.state == "installed":
                return before.to_dict()
            self.lifecycle.transition(before.state, "unloading")
            result = await adapter.unload_model(model_id)
            self.lifecycle.transition("unloading", result.state if result.ok else "failed")
            self._persist(result, "model_unload" if result.ok else "unload_failed")
            return result.to_dict()

    async def shutdown(self, runtime_id: str | None = None) -> list[dict]:
        adapters = [self.get_adapter(runtime_id)] if runtime_id else list(self._adapters.values())
        results = []
        for adapter in adapters:
            async with self._runtime_lock(adapter.runtime_id):
                result = await adapter.shutdown_owned_process()
                self._persist(result, "runtime_shutdown")
                results.append(result.to_dict())
        return results
