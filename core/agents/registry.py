"""Trusted application-side Agent Registry.

Only trusted application code may register agent definitions. Registration is
not a permission grant, not a capability source, and never reaches the API
surface as a write path. Unknown, disabled, or invalid definitions are rejected
before any run can be created.
"""
from __future__ import annotations

import copy

from core.agents.contracts import AgentDefinition, AgentDefinitionError
from core.repositories.agent_repository import AgentDefinitionRepository


class AgentRegistry:
    """Holds explicitly registered, versioned agent definitions."""

    def __init__(self, repository: AgentDefinitionRepository | None = None, *, clock=None) -> None:
        self.repository = repository
        self._definitions: dict = {}

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        """Validate and register one immutable definition from trusted code."""
        if not isinstance(definition, AgentDefinition):
            raise AgentDefinitionError("definition must be an AgentDefinition")
        key = (definition.agent_id, definition.version)
        if key in self._definitions:
            raise AgentDefinitionError(
                "An agent with this ID and version is already registered."
            )
        if self.repository is not None and self.repository.get(definition.agent_id, definition.version) is not None:
            raise AgentDefinitionError(
                "An agent with this ID and version is already persisted."
            )
        if self.repository is not None:
            definition = self.repository.register(definition)
        self._definitions[key] = copy.deepcopy(definition)
        return definition

    def get(self, agent_id: str, version: str) -> AgentDefinition:
        """Return a deep copy; callers can never mutate registered contracts.

        With a repository attached, lookups read through to persistence so
        definitions disabled or changed elsewhere are never served stale from
        the in-process cache.
        """
        key = (agent_id, version)
        if self.repository is not None:
            definition = self.repository.get(agent_id, version)
            if definition is None:
                raise AgentDefinitionError("The requested agent definition is unknown.")
            self._definitions[key] = definition
            return copy.deepcopy(definition)
        definition = self._definitions.get(key)
        if definition is None:
            raise AgentDefinitionError("The requested agent definition is unknown.")
        return copy.deepcopy(definition)

    def get_enabled(self, agent_id: str, version: str) -> AgentDefinition:
        definition = self.get(agent_id, version)
        if not definition.enabled:
            raise AgentDefinitionError("The requested agent definition is disabled.")
        return definition

    def list_published(self) -> tuple:
        """Return a safe, serializable catalog for API surfaces."""
        rows = []
        for key in sorted(self._definitions):
            definition = self._definitions[key]
            if self.repository is not None:
                persisted = self.repository.get(definition.agent_id, definition.version)
                if persisted is not None:
                    definition = persisted
            rows.append({
                "agent_id": definition.agent_id,
                "version": definition.version,
                "goal": definition.goal,
                "description": definition.description,
                "completion": {
                    "kind": definition.completion.kind,
                    "description": definition.completion.description,
                    "min_results": definition.completion.min_results,
                },
                "budgets": {
                    "max_iterations": definition.budgets.max_iterations,
                    "deadline_seconds": definition.budgets.deadline_seconds,
                    "max_tool_calls": definition.budgets.max_tool_calls,
                    "max_model_tokens": definition.budgets.max_model_tokens,
                    "max_input_bytes": definition.budgets.max_input_bytes,
                    "max_output_bytes": definition.budgets.max_output_bytes,
                },
                "allowed_tools": list(definition.allowed_tools),
                "allowed_models": list(definition.allowed_models),
                "data_scopes": list(definition.data_scopes),
                "approval_policy": definition.approval_policy,
                "enabled": definition.enabled,
            })
        return tuple(rows)

    def set_enabled(self, agent_id: str, version: str, enabled: bool) -> AgentDefinition:
        if not isinstance(enabled, bool):
            raise AgentDefinitionError("enabled must be a boolean")
        current = self.get(agent_id, version)
        if current.enabled is enabled and self.repository is None:
            return current
        if self.repository is None:
            updated = AgentDefinition(
                agent_id=current.agent_id,
                version=current.version,
                goal=current.goal,
                description=current.description,
                input_schema=current.input_schema,
                output_schema=current.output_schema,
                completion=current.completion,
                budgets=current.budgets,
                allowed_tools=current.allowed_tools,
                allowed_models=current.allowed_models,
                data_scopes=current.data_scopes,
                approval_policy=current.approval_policy,
                enabled=enabled,
            )
        else:
            updated = self.repository.set_enabled(agent_id, version, enabled)
            if updated is None:
                raise AgentDefinitionError("The requested agent definition is unknown.")
        self._definitions[(agent_id, version)] = updated
        return updated
