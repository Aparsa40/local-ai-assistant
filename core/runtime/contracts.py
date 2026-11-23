"""Stable contracts shared by local runtime adapters and orchestration."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RuntimeResult:
    ok: bool
    runtime_id: str
    state: str
    model_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    observed_at: str = field(default_factory=utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "runtime_id": self.runtime_id,
            "model_id": self.model_id,
            "state": self.state,
            "observed_at": self.observed_at,
            "data": self.data,
            "error": self.error,
        }


@dataclass(frozen=True)
class RuntimeExecutionContext:
    timeout_seconds: float = 30.0
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(ABC):
    runtime_id: str
    capabilities: frozenset[str] = frozenset()

    @abstractmethod
    async def ensure_available(self, auto_start: bool = True) -> RuntimeResult: ...

    @abstractmethod
    async def list_models(self) -> RuntimeResult: ...

    @abstractmethod
    async def inspect_model(self, model_id: str) -> RuntimeResult: ...

    @abstractmethod
    async def load_model(self, model_id: str, options: dict[str, Any] | None = None) -> RuntimeResult: ...

    @abstractmethod
    async def unload_model(self, model_id: str) -> RuntimeResult: ...

    async def shutdown_owned_process(self) -> RuntimeResult:
        return RuntimeResult(True, self.runtime_id, "ready", data={"process_stopped": False, "reason": "adapter_does_not_own_process"})
