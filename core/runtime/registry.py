"""Current-session registry for normalized runtime observations."""
from __future__ import annotations

from threading import RLock

from .contracts import ModelObservation, RuntimeProbe


class RuntimeRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runtimes: dict[str, RuntimeProbe] = {}
        self._models: dict[tuple[str, str], ModelObservation] = {}

    def record_runtime(self, observation: RuntimeProbe) -> None:
        with self._lock:
            self._runtimes[observation.runtime_id] = observation

    def get_runtime(self, runtime_id: str) -> RuntimeProbe | None:
        with self._lock:
            return self._runtimes.get(runtime_id)

    def record_models(self, observations: list[ModelObservation]) -> None:
        with self._lock:
            for observation in observations:
                self._models[(observation.runtime_id, observation.model_id)] = observation

    def get_model(self, runtime_id: str, model_id: str) -> ModelObservation | None:
        with self._lock:
            return self._models.get((runtime_id, model_id))

    def list_models(self, runtime_id: str) -> list[ModelObservation]:
        with self._lock:
            return [
                model for (owner, _), model in self._models.items()
                if owner == runtime_id
            ]
