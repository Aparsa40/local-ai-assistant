"""Persistence adapter for trusted, versioned agent definitions."""
from __future__ import annotations

from core.agents.contracts import (
    AgentBudgets,
    AgentDefinition,
    CompletionCriteria,
)
from core.agents.models import AgentDefinitionRecord
from .base import BaseRepository


class AgentDefinitionRepository(BaseRepository):
    """Owns ORM access and transaction boundaries for agent definitions."""

    @staticmethod
    def _to_contract(record: AgentDefinitionRecord) -> AgentDefinition:
        return AgentDefinition(
            agent_id=record.agent_id,
            version=record.version,
            goal=record.goal,
            description=record.description,
            input_schema=dict(record.input_schema or {}),
            output_schema=dict(record.output_schema or {}),
            completion=CompletionCriteria(
                kind=record.completion_kind,
                description=record.completion_description,
                min_results=int(record.completion_min_results),
            ),
            budgets=AgentBudgets(
                max_iterations=int(record.budget_max_iterations),
                deadline_seconds=int(record.budget_deadline_seconds),
                max_tool_calls=int(record.budget_max_tool_calls),
                max_model_tokens=int(record.budget_max_model_tokens),
                max_input_bytes=int(record.budget_max_input_bytes),
                max_output_bytes=int(record.budget_max_output_bytes),
            ),
            allowed_tools=tuple(record.allowed_tools or ()),
            allowed_models=tuple(record.allowed_models or ()),
            data_scopes=tuple(record.data_scopes or ()),
            approval_policy=record.approval_policy,
            enabled=bool(record.enabled),
        )

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        record = AgentDefinitionRecord(
            agent_id=definition.agent_id,
            version=definition.version,
            goal=definition.goal,
            description=definition.description,
            input_schema=definition.input_schema,
            output_schema=definition.output_schema,
            completion_kind=definition.completion.kind,
            completion_description=definition.completion.description,
            completion_min_results=definition.completion.min_results,
            budget_max_iterations=definition.budgets.max_iterations,
            budget_deadline_seconds=definition.budgets.deadline_seconds,
            budget_max_tool_calls=definition.budgets.max_tool_calls,
            budget_max_model_tokens=definition.budgets.max_model_tokens,
            budget_max_input_bytes=definition.budgets.max_input_bytes,
            budget_max_output_bytes=definition.budgets.max_output_bytes,
            allowed_tools=list(definition.allowed_tools),
            allowed_models=list(definition.allowed_models),
            data_scopes=list(definition.data_scopes),
            approval_policy=definition.approval_policy,
            enabled=definition.enabled,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def get(self, agent_id: str, version: str) -> AgentDefinition | None:
        record = (
            self.db.query(AgentDefinitionRecord)
            .filter(
                AgentDefinitionRecord.agent_id == agent_id,
                AgentDefinitionRecord.version == version,
            )
            .first()
        )
        return self._to_contract(record) if record else None

    def get_enabled(self, agent_id: str, version: str) -> AgentDefinition | None:
        definition = self.get(agent_id, version)
        if definition is None or not definition.enabled:
            return None
        return definition

    def list_all(self) -> tuple:
        records = (
            self.db.query(AgentDefinitionRecord)
            .order_by(AgentDefinitionRecord.agent_id, AgentDefinitionRecord.version.desc())
            .all()
        )
        return tuple(self._to_contract(record) for record in records)

    def set_enabled(self, agent_id: str, version: str, enabled: bool) -> AgentDefinition | None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        record = (
            self.db.query(AgentDefinitionRecord)
            .filter(
                AgentDefinitionRecord.agent_id == agent_id,
                AgentDefinitionRecord.version == version,
            )
            .first()
        )
        if record is None:
            return None
        record.enabled = enabled
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)
