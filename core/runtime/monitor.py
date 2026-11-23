"""Read-only runtime health and inventory snapshots."""
from __future__ import annotations


class RuntimeMonitor:
    def __init__(self, runtime_manager):
        self.runtime_manager = runtime_manager

    async def snapshot(self, runtime_id: str) -> dict:
        runtime = await self.runtime_manager.ensure_runtime(runtime_id, auto_start=False)
        if not runtime.get("ok"):
            return {"runtime": runtime, "models": [], "healthy": False}
        inventory = await self.runtime_manager.list_models(runtime_id, refresh=False)
        return {
            "runtime": runtime,
            "models": inventory.get("data", {}).get("models", []) if inventory.get("ok") else [],
            "healthy": bool(inventory.get("ok")),
            "inventory_error": inventory.get("error"),
        }
