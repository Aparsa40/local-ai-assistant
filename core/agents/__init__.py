"""Bounded, application-owned Agent Runtime.

Phase 6 introduces contracts, registry, lifecycle, and one deterministic
knowledge-analysis agent. The runtime is not a model provider and never
bypasses PermissionManager, ToolRuntime, or existing approval policies.
"""

__all__ = [
    "AgentRuntimeContainer",
    "AgentRegistry",
    "AgentLifecycleManager",
]


def __getattr__(name: str):
    if name == "AgentRegistry":
        from .registry import AgentRegistry
        return AgentRegistry
    if name == "AgentLifecycleManager":
        from .lifecycle import AgentLifecycleManager
        return AgentLifecycleManager
    if name == "AgentRuntimeContainer":
        from .bootstrap import AgentRuntimeContainer
        return AgentRuntimeContainer
    raise AttributeError(name)
