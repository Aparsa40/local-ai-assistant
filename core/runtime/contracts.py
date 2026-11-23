"""Engine-neutral runtime contracts and normalized observations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, Sequence


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeState(str, Enum):
    UNKNOWN = "unknown"
    CHECKING = "checking"
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    NOT_INSTALLED = "not_installed"
    FAILED = "failed"


class ModelState(str, Enum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    INSTALLED = "installed"
    LOADING = "loading"
    LOADED = "loaded"
    RUNNING = "running"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    FAILED = "failed"


@dataclass(frozen=True)
class RuntimeProbe:
    runtime_id: str
    state: RuntimeState
    endpoint_scope: str
    checked_at: str = field(default_factory=utc_now_iso)
    already_running: bool = False
    started_by_application: bool = False
    process_id: int | None = None
    error_category: str | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"state": self.state.value}


@dataclass(frozen=True)
class ModelObservation:
    runtime_id: str
    model_id: str
    state: ModelState = ModelState.UNKNOWN
    installed: bool | None = None
    loaded: bool | None = None
    observed_at: str = field(default_factory=utc_now_iso)
    source: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"state": self.state.value}


class RuntimeAdapter(Protocol):
    runtime_id: str

    async def probe(self) -> RuntimeProbe: ...
    async def ensure_ready(self, auto_start: bool = False) -> RuntimeProbe: ...
    async def list_installed_models(self) -> list[ModelObservation]: ...
    async def list_loaded_models(self) -> list[ModelObservation] | None: ...
    async def close(self) -> None: ...


class RuntimeAdapterFactory(Protocol):
    def __call__(self, **kwargs: Any) -> RuntimeAdapter: ...


def normalize_model_observations(
    runtime_id: str, models: Sequence[ModelObservation]
) -> list[ModelObservation]:
    """Validate adapter output and prevent cross-runtime model identity corruption."""
    normalized: list[ModelObservation] = []
    for model in models:
        if model.runtime_id != runtime_id or not model.model_id.strip():
            raise ValueError("Runtime adapter returned an invalid model identity.")
        normalized.append(model)
    return normalized
