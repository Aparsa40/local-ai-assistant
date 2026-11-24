"""Permission-checked scoped context assembly and capability binding.

The builder produces a plain, bounded RunContext for an agent run. It never
passes database sessions, repositories, provider credentials, filesystem
roots, or handler objects to agent code. Knowledge scope resolution and every
protected read are evaluated by PermissionManager first; cross-owner or
out-of-scope requests fail closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from core.agents.contracts import (
    AgentDefinition,
    AgentError,
    AgentInputError,
    AgentRun,
    AgentTask,
    DataScope,
)
from core.permissions.audit import AuditService
from core.permissions.manager import PermissionManager
from core.permissions.types import (
    AccessRequest,
    DecisionEffect,
    PermissionGrant,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.tools.registry import ToolRegistry


class AgentScopeDeniedError(AgentError, PermissionError):
    """A requested context scope or capability was not authorized."""


def validate_schema_value(value, schema, *, path: str = "$") -> None:
    """Validate one value against a bounded agent schema; raises AgentInputError."""
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            raise AgentInputError(path + " must be object.")
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            raise AgentInputError(path + " is missing required fields.")
        properties = schema.get("properties", {})
        if not schema.get("additionalProperties", False) and set(value) - set(properties):
            raise AgentInputError(path + " contains unsupported fields.")
        for name, item in value.items():
            if name in properties:
                validate_schema_value(item, properties[name], path=path + "." + name)
    elif schema_type == "array":
        if not isinstance(value, list):
            raise AgentInputError(path + " must be array.")
        for index, item in enumerate(value):
            validate_schema_value(item, schema["items"], path=path + "[" + str(index) + "]")
    elif schema_type == "string":
        if not isinstance(value, str):
            raise AgentInputError(path + " must be string.")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1000000):
            raise AgentInputError(path + " length is outside the allowed range.")
    elif schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise AgentInputError(path + " must be integer.")
    elif schema_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AgentInputError(path + " must be number.")
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            raise AgentInputError(path + " must be boolean.")
    elif schema_type == "null":
        if value is not None:
            raise AgentInputError(path + " must be null.")
    if "enum" in schema and value not in schema["enum"]:
        raise AgentInputError(path + " is not an allowed value.")


@dataclass(frozen=True, slots=True)
class BoundCapability:
    """One least-privilege tool binding derived from the trusted registry."""

    tool_id: str
    version: str
    resource_type: ResourceType
    operation: PermissionOperation
    risk_class: str

    def public_view(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "version": self.version,
            "resource_type": self.resource_type.value,
            "operation": self.operation.value,
            "risk_class": self.risk_class,
        }


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """Exact tool capabilities for one run; never contains handler objects."""

    run_id: str
    capabilities: tuple = ()
    knowledge_scopes: tuple = ()

    def capability_for(self, tool_id: str) -> BoundCapability | None:
        for capability in self.capabilities:
            if capability.tool_id == tool_id:
                return capability
        return None

    def public_view(self) -> dict:
        return {
            "run_id": self.run_id,
            "capabilities": [item.public_view() for item in self.capabilities],
            "knowledge_scopes": [
                {"domain": "knowledge", "scope_type": scope.scope_type, "scope_id": scope.scope_id, "owner_id": scope.owner_id}
                for scope in self.knowledge_scopes
            ],
        }


@dataclass(frozen=True, slots=True)
class RunContext:
    """The total visible surface of one agent run; plain data only."""

    run_id: str
    task_id: str
    agent_id: str
    agent_version: str
    owner_id: str
    trace_id: str
    goal: str
    task_title: str
    query: str
    payload: dict
    binding: CapabilityBinding
    input_bytes: int

    def public_view(self) -> dict:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "owner_id": self.owner_id,
            "trace_id": self.trace_id,
            "goal": self.goal,
            "task_title": self.task_title,
            "binding": self.binding.public_view(),
            "input_bytes": self.input_bytes,
        }


class AgentContextBuilder:
    """Builds explicit, permission-checked run contexts."""

    def __init__(
        self,
        permission_manager: PermissionManager,
        *,
        audit_service: AuditService | None = None,
    ) -> None:
        self.permission_manager = permission_manager
        self.audit_service = audit_service

    def build(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        task: AgentTask,
        *,
        binding: CapabilityBinding,
    ) -> RunContext:
        if run.owner_id != task.owner_id:
            raise AgentScopeDeniedError("Run owner does not match the task owner.")
        if run.agent_id != definition.agent_id or run.agent_version != definition.version:
            raise AgentScopeDeniedError("Run does not match the registered definition version.")

        try:
            payload = dict(task.payload or {})
            self._validate_input_bytes(payload, definition)
            validate_schema_value(payload, definition.input_schema)
        except AgentInputError:
            raise
        except (TypeError, ValueError) as exc:
            raise AgentInputError("Task payload violates the agent input schema.") from exc

        knowledge_scopes = [
            scope for scope in task.data_scopes if scope.domain == "knowledge"
        ]
        # Every knowledge scope must pass an explicit permission check before use.
        for scope in knowledge_scopes:
            self._require_scope_read(run, scope)

        query = str(payload.get("query", "")).strip()
        capsule = (
            "Agent goal: " + definition.goal + "\n"
            "Task: " + task.title + "\n"
            "Request: " + query
        )
        if len(capsule.encode("utf-8")) > definition.budgets.max_input_bytes:
            raise AgentInputError("Bound context capsule exceeds the agent input budget.")

        return RunContext(
            run_id=run.run_id,
            task_id=run.task_id,
            agent_id=run.agent_id,
            agent_version=run.agent_version,
            owner_id=run.owner_id,
            trace_id=run.trace_id,
            goal=definition.goal,
            task_title=task.title,
            query=query,
            payload=payload,
            binding=binding,
            input_bytes=len(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")),
        )

    def _validate_input_bytes(self, payload: dict, definition: AgentDefinition) -> None:
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise AgentInputError("Task payload must be JSON-serializable.") from exc
        if len(encoded.encode("utf-8")) > definition.budgets.max_input_bytes:
            raise AgentInputError("Task payload exceeds the agent input budget.")

    def _require_scope_read(self, run: AgentRun, scope: DataScope) -> None:
        try:
            scope_enum = ScopeType(scope.scope_type)
        except ValueError as exc:
            raise AgentScopeDeniedError("The requested scope type is unsupported.") from exc
        request = AccessRequest(
            subject=PermissionSubject(SubjectType.AGENT_RUN, run.run_id),
            resource=PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope.scope_id),
            operation=PermissionOperation.READ,
            scope=PermissionScope(scope_enum, scope.scope_id, scope.owner_id),
        )
        decision = self.permission_manager.authorize(request)
        if self.audit_service is not None:
            self.audit_service.record(
                event_type="agent_context_scope_decision",
                request_id=request.request_id,
                outcome=decision.effect.value,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                metadata={
                    "decision": decision.effect.value,
                    "reason_code": decision.reason_code,
                    "grant_id": decision.grant_id or "",
                },
            )
        if decision.effect is not DecisionEffect.ALLOW:
            raise AgentScopeDeniedError(
                "Knowledge scope access was denied for this run."
            )


class CapabilityResolver:
    """Binds run subjects to exact tool grants for read-only capabilities."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def resolve(self, definition: AgentDefinition, run: AgentRun, task: AgentTask) -> CapabilityBinding:
        catalog = {entry["tool_id"]: entry for entry in self.tool_registry.public_catalog()}
        capabilities = []
        for tool_id in definition.allowed_tools:
            entry = catalog.get(tool_id)
            if entry is None:
                raise AgentScopeDeniedError(
                    "Allowed tool is not registered or is disabled: " + tool_id
                )
            if entry["operation"] != PermissionOperation.READ.value:
                raise AgentScopeDeniedError(
                    "Phase 6 capability binding supports read-only tools only."
                )
            capabilities.append(
                BoundCapability(
                    tool_id=entry["tool_id"],
                    version=str(entry["version"]),
                    resource_type=ResourceType(entry["resource_type"]),
                    operation=PermissionOperation(entry["operation"]),
                    risk_class=str(entry["risk_class"]),
                )
            )
        knowledge_scopes = tuple(
            scope for scope in task.data_scopes if scope.domain == "knowledge"
        )
        return CapabilityBinding(
            run_id=run.run_id,
            capabilities=tuple(capabilities),
            knowledge_scopes=knowledge_scopes,
        )

    def issue_capability_grants(
        self,
        definition: AgentDefinition,
        run: AgentRun,
        task: AgentTask,
        binding: CapabilityBinding,
        *,
        issuer: PermissionSubject,
        managed: PermissionManager,
        audit_service: AuditService | None = None,
    ) -> int:
        """Persist exact per-run grants for read-only knowledge capabilities.

        Trusted application code issues these grants on behalf of the user's
        explicit run request; agent or run subjects can never issue grants.
        Each grant is exact: subject (agent_run, run_id), one knowledge scope
        resource, the read operation, and the task-declared scope.
        """
        issued = 0
        for capability in binding.capabilities:
            if capability.resource_type is not ResourceType.KNOWLEDGE_SOURCE:
                continue
            if capability.operation is not PermissionOperation.READ:
                continue
            for scope in binding.knowledge_scopes:
                grant = PermissionGrant(
                    grant_id=uuid4().hex,
                    subject=PermissionSubject(SubjectType.AGENT_RUN, run.run_id),
                    resource=PermissionResource(
                        ResourceType.KNOWLEDGE_SOURCE, scope.scope_id
                    ),
                    operation=capability.operation,
                    scope=PermissionScope(
                        ScopeType(scope.scope_type), scope.scope_id, scope.owner_id
                    ),
                    issued_by=issuer.subject_id,
                )
                managed.issue_grant(grant, issuer=issuer)
                issued += 1
                if audit_service is not None:
                    audit_service.record(
                        event_type="agent_capability_grant_issued",
                        request_id=run.trace_id,
                        outcome="issued",
                        subject=grant.subject,
                        resource=grant.resource,
                        operation=grant.operation,
                        metadata={"grant_id": grant.grant_id, "tool_id": capability.tool_id},
                    )
        return issued
