"""Typed, immutable orchestration contracts for the Phase 7 Supervisor.

These dataclasses describe goals, plans, task nodes, dependencies,
assignments, handoffs, evidence, and aggregate results. They are pure
application-side contracts: they never grant permissions, never execute
tools, and never invoke models.

Threat-model notes baked into the contracts (WP-7.1):
- Plans produced by models are untrusted: every plan field has explicit byte
  limits, identifiers reject wildcard and control characters, and acceptance
  requires application-side policy checks before persistence.
- Cyclic dependency graphs, invalid dependency references, and duplicate task
  identifiers are rejected before a plan can be persisted or scheduled.
- Handoff payloads are JSON-only with hard size limits.
- Assignment and evidence records preserve provenance so an assignment
  decision is always explainable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from core.agents.contracts import (
    AGENT_ID_PATTERN,
    HEX32_PATTERN,
    MAX_INPUT_BYTES,
    SEMVER_PATTERN,
    CompletionCriteria,
    DataScope,
)

MAX_PLAN_NODES = 32
MAX_HANDOFF_BYTES = 64 * 1024
MAX_PLAN_PAYLOAD_BYTES = 32 * 1024

AGENT_ID_PATTERN = AGENT_ID_PATTERN
SEMVER_PATTERN = SEMVER_PATTERN
HEX32_PATTERN = HEX32_PATTERN


class OrchestrationError(Exception):
    """Base class for expected Supervisor orchestration errors."""


class PlanValidationError(OrchestrationError, ValueError):
    """A plan violates a structural, dependency, or budget constraint."""


class HandoffValidationError(OrchestrationError, ValueError):
    """A handoff envelope violates a schema or size constraint."""


class OrchestrationNodeStateError(OrchestrationError, ValueError):
    """A node or dependency transition is not legal for the current state."""


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class DependencyStatus(str, Enum):
    PENDING = "pending"
    SATISFIED = "satisfied"
    UNSATISFIABLE = "unsatisfiable"


class EvidenceLevel(str, Enum):
    """Evidence level for a capability assertion (WP-7.3)."""

    UNKNOWN = "unknown"        # No application-side evidence exists.
    DECLARED = "declared"      # A trusted definition declares the capability.
    VERIFIED = "verified"      # The runtime positively verified the capability.


# Legal node lifecycle transitions. Any transition not listed here is rejected.
NODE_TRANSITIONS: dict[NodeStatus, frozenset[NodeStatus]] = {
    NodeStatus.PENDING: frozenset({NodeStatus.SCHEDULED, NodeStatus.CANCELLED, NodeStatus.SKIPPED}),
    NodeStatus.SCHEDULED: frozenset({NodeStatus.RUNNING, NodeStatus.CANCELLED}),
    NodeStatus.RUNNING: frozenset({NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.CANCELLED}),
    NodeStatus.COMPLETED: frozenset(),
    NodeStatus.FAILED: frozenset({NodeStatus.PENDING}),  # One bounded retry reset.
    NodeStatus.CANCELLED: frozenset({NodeStatus.PENDING}),  # Requeue on restart recovery.
    NodeStatus.SKIPPED: frozenset(),
}


def can_transition_node(current: NodeStatus, target: NodeStatus) -> bool:
    if not isinstance(current, NodeStatus) or not isinstance(target, NodeStatus):
        raise ValueError("node transition states must be NodeStatus values")
    return target in NODE_TRANSITIONS[current]


def require_node_transition(current: NodeStatus, target: NodeStatus) -> None:
    if not can_transition_node(current, target):
        raise OrchestrationNodeStateError(
            "Node transition " + current.value + " -> " + target.value + " is not allowed."
        )


# Legal dependency states. Terminal states absorb; unsatisfiable is never reset.
DEPENDENCY_TRANSITIONS: dict[DependencyStatus, frozenset[DependencyStatus]] = {
    DependencyStatus.PENDING: frozenset({DependencyStatus.SATISFIED, DependencyStatus.UNSATISFIABLE}),
    DependencyStatus.SATISFIED: frozenset(),
    DependencyStatus.UNSATISFIABLE: frozenset(),
}


def can_transition_dependency(current: DependencyStatus, target: DependencyStatus) -> bool:
    if not isinstance(current, DependencyStatus) or not isinstance(target, DependencyStatus):
        raise ValueError("dependency transition states must be DependencyStatus values")
    return target in DEPENDENCY_TRANSITIONS[current]


def _required_text(value, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise PlanValidationError(field_name + " must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise PlanValidationError(field_name + " must contain 1.." + str(maximum) + " characters")
    if any(ord(char) < 32 for char in normalized):
        raise PlanValidationError(field_name + " contains control characters")
    return normalized


def _required_hex32(value, field_name: str) -> str:
    if not isinstance(value, str) or not HEX32_PATTERN.fullmatch(value):
        raise PlanValidationError(field_name + " must be a 32-character lowercase hex identifier")
    return value


def _required_identifier(value, field_name: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise PlanValidationError(field_name + " must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise PlanValidationError(field_name + " must contain 1.." + str(maximum) + " characters")
    if normalized in {"*", "**", "all", "any"}:
        raise PlanValidationError(field_name + " cannot use wildcard identifiers")
    if any(ord(char) < 32 for char in normalized):
        raise PlanValidationError(field_name + " contains control characters")
    return normalized


def _bounded_json(value, field_name: str, *, maximum: int) -> dict:
    if not isinstance(value, dict):
        raise PlanValidationError(field_name + " must be a JSON object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise PlanValidationError(field_name + " must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise PlanValidationError(field_name + " exceeds the " + str(maximum) + " byte limit")
    return value


@dataclass(frozen=True, slots=True)
class OrchestrationBudgets:
    """Hard orchestration ceilings; every allocatable resource is bounded."""

    max_nodes: int = 8
    max_wall_clock_seconds: int = 1800
    per_task_deadline_seconds: int = 300
    max_retries_per_task: int = 1
    max_active_tasks: int = 1

    def __post_init__(self) -> None:
        for name, value, maximum, minimum in (
            ("max_nodes", self.max_nodes, MAX_PLAN_NODES, 1),
            ("max_wall_clock_seconds", self.max_wall_clock_seconds, 3600, 1),
            ("per_task_deadline_seconds", self.per_task_deadline_seconds, 3600, 1),
            ("max_retries_per_task", self.max_retries_per_task, 3, 0),
            ("max_active_tasks", self.max_active_tasks, 8, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise PlanValidationError(
                    name + " must be an integer between " + str(minimum) + " and " + str(maximum)
                )


@dataclass(frozen=True, slots=True)
class Goal:
    """A bounded user-owned objective; never a permission grant."""

    goal_id: str
    owner_id: str
    description: str
    success_criteria: str
    data_scopes: tuple = ()
    tool_scopes: tuple = ()
    budgets: OrchestrationBudgets = field(default_factory=OrchestrationBudgets)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.goal_id, "goal_id")
        object.__setattr__(self, "owner_id", _required_identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "description", _required_text(self.description, "goal description", maximum=2000))
        object.__setattr__(
            self, "success_criteria", _required_text(self.success_criteria, "success criteria", maximum=500)
        )
        if not isinstance(self.data_scopes, tuple) or len(self.data_scopes) > 10:
            raise PlanValidationError("data_scopes must be a tuple of at most 10 explicit scopes")
        for scope in self.data_scopes:
            if not isinstance(scope, DataScope):
                raise PlanValidationError("each data scope must be a DataScope")
            if scope.owner_id != self.owner_id:
                raise PlanValidationError("goal scopes must belong to the goal owner")
        if not isinstance(self.tool_scopes, tuple) or len(self.tool_scopes) > 20:
            raise PlanValidationError("tool_scopes must be a tuple of at most 20 tool identifiers")
        for tool in self.tool_scopes:
            if not isinstance(tool, str) or not tool or len(tool) > 80 or any(ord(c) < 32 for c in tool):
                raise PlanValidationError("tool_scopes contain an invalid tool identifier")
        if not isinstance(self.budgets, OrchestrationBudgets):
            raise PlanValidationError("budgets must be an OrchestrationBudgets")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PlanValidationError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Provenanced evidence for one assignment, run, or handoff assertion."""

    evidence_id: str
    kind: str
    subject: str
    claim: str
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.evidence_id, "evidence_id")
        if self.kind not in {
            "declared_capability", "verified_tool", "model_catalog",
            "run_outcome", "handoff_reference", "policy_check",
        }:
            raise PlanValidationError("evidence kind is not supported")
        object.__setattr__(self, "subject", _required_identifier(self.subject, "evidence subject", maximum=160))
        object.__setattr__(self, "claim", _required_text(self.claim, "evidence claim", maximum=300))
        if not isinstance(self.collected_at, datetime) or self.collected_at.tzinfo is None:
            raise PlanValidationError("collected_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TaskNode:
    """One bounded plan step over a registered agent; per-node state is versioned."""

    node_id: str
    plan_id: str
    ordinal: int
    title: str
    required_capabilities: tuple
    acceptance: CompletionCriteria
    payload: dict
    data_scopes: tuple = ()
    tool_scopes: tuple = ()
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    max_retries: int = 0
    agent_id: str | None = None
    agent_version: str | None = None
    run_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.node_id, "node_id")
        _required_hex32(self.plan_id, "plan_id")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise PlanValidationError("ordinal must be a non-negative integer")
        object.__setattr__(self, "title", _required_text(self.title, "node title", maximum=200))
        if not isinstance(self.required_capabilities, tuple) or len(self.required_capabilities) > 20:
            raise PlanValidationError("required_capabilities must be a tuple of at most 20 strings")
        for capability in self.required_capabilities:
            if not isinstance(capability, str) or not capability or len(capability) > 80:
                raise PlanValidationError("required capabilities must be bounded strings")
            if any(ord(char) < 32 for char in capability):
                raise PlanValidationError("required capabilities contain control characters")
        if not isinstance(self.acceptance, CompletionCriteria):
            raise PlanValidationError("acceptance must be a CompletionCriteria")
        _bounded_json(self.payload, "node payload", maximum=MAX_PLAN_PAYLOAD_BYTES)
        if not isinstance(self.data_scopes, tuple) or len(self.data_scopes) > 10:
            raise PlanValidationError("data_scopes must be a tuple of at most 10 explicit scopes")
        for scope in self.data_scopes:
            if not isinstance(scope, DataScope):
                raise PlanValidationError("each data scope must be a DataScope")
        if not isinstance(self.tool_scopes, tuple) or len(self.tool_scopes) > 20:
            raise PlanValidationError("tool_scopes must be a tuple of at most 20 tool identifiers")
        for tool in self.tool_scopes:
            if not isinstance(tool, str) or not tool or len(tool) > 80 or any(ord(c) < 32 for c in tool):
                raise PlanValidationError("tool_scopes contain an invalid tool identifier")
        if not isinstance(self.status, NodeStatus):
            raise PlanValidationError("status must be a NodeStatus")
        for name, value, minimum in (("attempts", self.attempts, 0), ("max_retries", self.max_retries, 0)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > 3:
                raise PlanValidationError(name + " must be an integer between " + str(minimum) + " and " + str(3))
        for name in ("agent_id", "agent_version", "run_id", "error_code", "error_message"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) > 160):
                raise PlanValidationError(name + " is invalid or too long")
        if self.agent_id is not None and not AGENT_ID_PATTERN.fullmatch(self.agent_id):
            raise PlanValidationError("assigned agent_id is invalid")
        if self.agent_version is not None and not SEMVER_PATTERN.fullmatch(self.agent_version):
            raise PlanValidationError("assigned agent_version is invalid")
        if self.run_id is not None and not HEX32_PATTERN.fullmatch(self.run_id):
            raise PlanValidationError("assigned run_id is invalid")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PlanValidationError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Dependency:
    """One directed plan dependency; Phase 7 supports all-success policies only."""

    dependency_id: str
    plan_id: str
    node_id: str
    depends_on: str
    policy: str = "all_success"
    status: DependencyStatus = DependencyStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.dependency_id, "dependency_id")
        _required_hex32(self.plan_id, "plan_id")
        _required_hex32(self.node_id, "node_id")
        _required_hex32(self.depends_on, "depends_on")
        if self.node_id == self.depends_on:
            raise PlanValidationError("a task cannot depend on itself")
        if self.policy != "all_success":
            raise PlanValidationError("only the all_success dependency policy is supported")
        if not isinstance(self.status, DependencyStatus):
            raise PlanValidationError("status must be a DependencyStatus")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PlanValidationError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Assignment:
    """One explainable assignment decision preserved with its evidence."""

    assignment_id: str
    plan_id: str
    node_id: str
    decision: str  # assigned | denied
    agent_id: str | None = None
    agent_version: str | None = None
    run_id: str | None = None
    reasons: tuple = ()
    evidence: tuple = ()
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.assignment_id, "assignment_id")
        _required_hex32(self.plan_id, "plan_id")
        _required_hex32(self.node_id, "node_id")
        if self.decision not in {"assigned", "denied"}:
            raise PlanValidationError("assignment decision must be assigned or denied")
        for name in ("agent_id", "agent_version", "run_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) > 160):
                raise PlanValidationError(name + " is invalid or too long")
        if self.decision == "assigned" and self.agent_id is not None and not AGENT_ID_PATTERN.fullmatch(self.agent_id):
            raise PlanValidationError("assigned agent_id is invalid")
        if self.decision == "assigned" and self.agent_id is None:
            raise PlanValidationError("an assigned decision must record the agent")
        if not isinstance(self.reasons, tuple) or len(self.reasons) > 20:
            raise PlanValidationError("reasons must be a tuple of at most 20 strings")
        for reason in self.reasons:
            if not isinstance(reason, str) or not reason or len(reason) > 300:
                raise PlanValidationError("assignment reasons must be bounded strings")
        if not isinstance(self.evidence, tuple) or len(self.evidence) > 20:
            raise PlanValidationError("evidence must be a tuple of at most 20 Evidence values")
        for item in self.evidence:
            if not isinstance(item, Evidence):
                raise PlanValidationError("assignment evidence must contain Evidence values")
        if not isinstance(self.decided_at, datetime) or self.decided_at.tzinfo is None:
            raise PlanValidationError("decided_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Handoff:
    """Versioned typed handoff envelope between one run and the plan."""

    handoff_id: str
    plan_id: str
    node_id: str
    from_run_id: str
    envelope_version: str  # must be "orchestration.handoff/1"
    payload: dict
    status: str  # complete | partial | incomplete
    evidence: tuple = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.handoff_id, "handoff_id")
        _required_hex32(self.plan_id, "plan_id")
        _required_hex32(self.node_id, "node_id")
        _required_hex32(self.from_run_id, "from_run_id")
        if self.envelope_version != "orchestration.handoff/1":
            raise HandoffValidationError("unsupported handoff envelope version")
        _bounded_json(self.payload, "handoff payload", maximum=MAX_HANDOFF_BYTES)
        if self.status not in {"complete", "partial", "incomplete"}:
            raise HandoffValidationError("handoff status must be complete, partial, or incomplete")
        if not isinstance(self.evidence, tuple) or len(self.evidence) > 20:
            raise HandoffValidationError("handoff evidence must be a tuple of at most 20 Evidence values")
        for item in self.evidence:
            if not isinstance(item, Evidence):
                raise HandoffValidationError("handoff evidence must contain Evidence values")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise HandoffValidationError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Plan:
    """A valid DAG of bounded task nodes; plans are versioned and auditable."""

    plan_id: str
    goal_id: str
    parent_run_id: str
    parent_task_id: str
    owner_id: str
    revision: int
    status: PlanStatus
    nodes: tuple
    dependencies: tuple
    budgets: OrchestrationBudgets = field(default_factory=OrchestrationBudgets)
    acceptance: CompletionCriteria | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 0

    def __post_init__(self) -> None:
        _required_hex32(self.plan_id, "plan_id")
        _required_hex32(self.goal_id, "goal_id")
        _required_hex32(self.parent_run_id, "parent_run_id")
        _required_hex32(self.parent_task_id, "parent_task_id")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or not 0 <= self.revision <= 8:
            raise PlanValidationError("revision must be an integer between 0 and 8")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or not 0 <= self.version <= 1000000:
            raise PlanValidationError("version must be a non-negative integer")
        if not isinstance(self.status, PlanStatus):
            raise PlanValidationError("status must be a PlanStatus")
        if not isinstance(self.nodes, tuple) or any(not isinstance(item, TaskNode) for item in self.nodes):
            raise PlanValidationError("nodes must be a tuple of TaskNode values")
        if not isinstance(self.dependencies, tuple) or any(not isinstance(item, Dependency) for item in self.dependencies):
            raise PlanValidationError("dependencies must be a tuple of Dependency values")
        if not isinstance(self.budgets, OrchestrationBudgets):
            raise PlanValidationError("budgets must be an OrchestrationBudgets")
        if self.acceptance is not None and not isinstance(self.acceptance, CompletionCriteria):
            raise PlanValidationError("acceptance must be a CompletionCriteria or None")
        for name, value in (("error_code", self.error_code), ("error_message", self.error_message)):
            if value is not None and (not isinstance(value, str) or len(value) > 300):
                raise PlanValidationError(name + " is invalid or too long")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PlanValidationError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AggregateResult:
    """Aggregated plan outcome; conflicts and missing evidence stay visible."""

    plan_id: str
    parent_run_id: str
    status: str  # completed | partial | failed | cancelled
    outcomes: tuple
    conflicts: tuple = ()
    missing_evidence: tuple = ()
    produced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_hex32(self.plan_id, "plan_id")
        _required_hex32(self.parent_run_id, "parent_run_id")
        if self.status not in {"completed", "partial", "failed", "cancelled"}:
            raise PlanValidationError("aggregate status is not supported")
        if not isinstance(self.outcomes, tuple) or len(self.outcomes) > MAX_PLAN_NODES:
            raise PlanValidationError("outcomes must be a tuple of at most " + str(MAX_PLAN_NODES) + " entries")
        for item in self.outcomes:
            if not isinstance(item, dict) or "node_id" not in item or "status" not in item:
                raise PlanValidationError("each outcome must record node_id and status")
        for name, value in (("conflicts", self.conflicts), ("missing_evidence", self.missing_evidence)):
            if not isinstance(value, tuple) or len(value) > 100:
                raise PlanValidationError(name + " must be a tuple of at most 100 strings")
            for item in value:
                if not isinstance(item, str) or not item or len(item) > 300:
                    raise PlanValidationError(name + " entries must be bounded strings")
        if not isinstance(self.produced_at, datetime) or self.produced_at.tzinfo is None:
            raise PlanValidationError("produced_at must be timezone-aware")


def new_goal_id() -> str:
    return uuid4().hex


def new_plan_id() -> str:
    return uuid4().hex


def new_node_id() -> str:
    return uuid4().hex


def new_dependency_id() -> str:
    return uuid4().hex


def new_assignment_id() -> str:
    return uuid4().hex


def new_evidence_id() -> str:
    return uuid4().hex


def new_handoff_id() -> str:
    return uuid4().hex
