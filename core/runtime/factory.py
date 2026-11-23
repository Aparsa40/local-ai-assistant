"""Composition root for the currently supported local runtime adapters."""
from __future__ import annotations

from .manager import RuntimeManager
from .ollama_adapter import OllamaRuntimeAdapter
from .repository import RuntimeRepository


def build_runtime_manager(config_loader, session_factory) -> RuntimeManager:
    # Reuse the process controller already used by provider intelligence so ownership
    # cannot be split across two independent controllers in the same application.
    from ..provider_intelligence import _LOCAL_RUNTIME_CONTROLLER

    config = config_loader() or {}
    ollama_config = (config.get("providers_config") or {}).get("ollama", {})
    adapter = OllamaRuntimeAdapter(
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        controller=_LOCAL_RUNTIME_CONTROLLER,
        config_loader=config_loader,
    )
    return RuntimeManager(
        adapters=[adapter],
        repository=RuntimeRepository(session_factory),
    )
