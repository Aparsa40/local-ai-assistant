"""Conservative admission control; unknown hardware telemetry stays unknown."""
from __future__ import annotations


class ResourceManager:
    def __init__(self, max_loaded_models: int | None = None):
        self.max_loaded_models = max_loaded_models

    def can_load(self, currently_loaded: int) -> tuple[bool, str | None]:
        if self.max_loaded_models is not None and currently_loaded >= self.max_loaded_models:
            return False, "Configured maximum number of loaded models would be exceeded."
        return True, None
