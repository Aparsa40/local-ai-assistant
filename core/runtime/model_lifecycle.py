"""Validated model lifecycle state transitions."""
from __future__ import annotations


class ModelLifecycle:
    ALLOWED = {
        "discovered": {"installed", "loading", "failed", "unknown"},
        "installed": {"loading", "unloading", "installed", "unknown", "failed"},
        "loading": {"loaded", "installed", "unknown", "failed"},
        "loaded": {"running", "unloading", "loaded", "unknown", "failed"},
        "running": {"loaded", "unloading", "failed", "unknown"},
        "unloading": {"installed", "loaded", "unknown", "failed"},
        "failed": {"installed", "loading", "unloading", "unknown", "failed"},
        "unknown": {"discovered", "installed", "loading", "loaded", "unloading", "unknown", "failed"},
    }

    @classmethod
    def transition(cls, current: str, target: str) -> str:
        if target not in cls.ALLOWED.get(current, set()):
            raise ValueError(f"Invalid model lifecycle transition: {current} -> {target}")
        return target
