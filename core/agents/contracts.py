"""Typed, immutable Agent Runtime contracts and lifecycle transitions.

These dataclasses describe agent definitions, tasks, runs, steps, checkpoints,
and structured outcomes. They are pure application-side types: they never grant
permissions, never execute tools, and never invoke models by themselves.

Threat-model notes baked into the contracts (WP-6.1):
- Untrusted code cannot inflate definitions: only trusted application code
  imports and calls AgentRegistry.register.
- Model output and task input are untrusted; every schema has explicit byte
  limits, and identifiers reject wildcard and control characters.
- Stale or replayed transitions are rejected through the explicit transition
  table plus per-run optimistic version checks in persistence.
- Checkpoint payloads are JSON-only with a hard size limit.
- Agent metadata is never a permission: PermissionManager evaluates every
  exact request.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

AGENT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{1,79}")
SEMVER_PATTERN = re.compile(r"\d+\.\d+\.\d+")
HEX32_PATTERN = re.compile(r"[0-9a-f]{32}")

MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
MAX_CHECKPOINT_BYTES = 128 * 1024
MAX_SCHEMA_BYTES = 16 * 1024

_ALLOWED_SCHEMA_TYPES = {"object", "string", "integer", "number", "boolean", "array", "null"}
_ALLOWED_SCHEMA_KEYS = {
    "type", "properties", "required", "additionalProperties", "enum",
    "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "items",
}
_ALLOWED_DATA_DOMAINS = {"conversation", "knowledge", "memory"}
_ALLOWED_APPROVAL_POLICIES = {"explicit"}
_ALLOWED_COMPLETION_KINDS = {"deterministic_steps_done", "sources_collected", "structured_result_present"}


class AgentError(Exception):
    """Base class for expected Agent Runtime errors."""


class AgentDefinitionError(AgentError, ValueError):
    """An agent definition violates its contract."""


class AgentTransitionError(AgentError, ValueError):
    """A lifecycle transition is not legal for the current state."""


class AgentInputError(AgentError, ValueError):
    """Task input or run payload violates a validated contract."""


class AgentConcurrencyError(AgentError, RuntimeError):
    """Optimistic concurrency detected: persisted state changed underneath the caller."""


class AgentRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    OPEN = "open"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class StepKind(str, Enum):
    PLAN = "plan"
    ACT = "act"
    OBSERVE = "observe"
    EVALUATE = "evaluate"


class StepStatus(str, Enum):
    OK = "ok"
    REJECTED = "rejected"
    PAUSED = "paused"
    FAILED = "failed"


class StopReason(str, Enum):
    """Truthful, bounded reasons an execution loop stopped."""

    COMPLETED = "completed"
    PAUSED_BY_REQUEST = "paused_by_request"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    CANCELLED = "cancelled"
    FAILED = "failed"
    MAX_ITERATIONS = "max_iterations"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TOOL_CALL_LIMIT = "tool_call_limit"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    OUTPUT_LIMIT = "output_limit"
    MODEL_UNAVAILABLE = "model_unavailable"
    PERMISSION_DENIED = "permission_denied"


# Legal lifecycle transitions. Any transition not listed here is rejected.
TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.PENDING: frozenset({AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED}),
    AgentRunStatus.RUNNING: frozenset({
        AgentRunStatus.PAUSED,
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }),
    AgentRunStatus.PAUSED: frozenset({AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED}),
    AgentRunStatus.SUCCEEDED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.CANCELLED: frozenset(),
}


def can_transition(current: AgentRunStatus, target: AgentRunStatus) -> bool:
    if not isinstance(current, AgentRunStatus) or not isinstance(target, AgentRunStatus):
        raise ValueError("transition states must be AgentRunStatus values")
    return target in TRANSITIONS[current]


def require_transition(current: AgentRunStatus, target: AgentRunStatus) -> None:
    if not can_transition(current, target):
        raise AgentTransitionError(
            "Transition " + current.value + " -> " + target.value + " is not allowed."
        )


def _required_text(value, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise AgentDefinitionError(field_name + " must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise AgentDefinitionError(field_name + " must contain 1.." + str(maximum) + " characters")
    if any(ord(char) < 32 for char in normalized):
        raise AgentDefinitionError(field_name + " contains control characters")
    return normalized


def _required_identifier(value, field_name: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise ValueError(field_name + " must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(field_name + " must contain 1.." + str(maximum) + " characters")
    if normalized in {"*", "**", "all", "any"}:
        raise ValueError(field_name + " cannot use wildcard identifiers")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError(field_name + " contains control characters")
    return normalized


def _bounded_json(value, field_name: str, *, maximum: int) -> dict:
    if not isinstance(value, dict):
        raise AgentDefinitionError(field_name + " must be a JSON object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise AgentDefinitionError(field_name + " must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise AgentDefinitionError(field_name + " exceeds the " + str(maximum) + " byte limit")
    return value


def validate_bounded_schema(schema, field_name: str, *, depth: int = 0) -> None:
    """Whitelisted, bounded JSON-schema check mirroring the Tool Registry rules."""
    if depth > 8:
        raise AgentDefinitionError(field_name + " nesting exceeds depth 8")
    if not isinstance(schema, dict) or set(schema) - _ALLOWED_SCHEMA_KEYS:
        raise AgentDefinitionError(field_name + " contains unsupported schema keywords")
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _ALLOWED_SCHEMA_TYPES:
        raise AgentDefinitionError(field_name + " must declare a supported type")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], int) or schema[key] < 0):
            raise AgentDefinitionError(field_name + "." + key + " must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            raise AgentDefinitionError(field_name + "." + key + " must be numeric")
    if schema.get("minimum") is not None and schema.get("maximum") is not None and schema["minimum"] > schema["maximum"]:
        raise AgentDefinitionError(field_name + ".minimum cannot exceed maximum")
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 100:
            raise AgentDefinitionError(field_name + ".properties must be a bounded object")
        required = schema.get("required", [])
        if not isinstance(required, list) or len(required) > 100 or any(not isinstance(item, str) for item in required):
            raise AgentDefinitionError(field_name + ".required must be a bounded string list")
        if len(set(required)) != len(required) or not set(required).issubset(properties):
            raise AgentDefinitionError(field_name + ".required must reference declared properties")
        if not isinstance(schema.get("additionalProperties", False), bool):
            raise AgentDefinitionError(field_name + ".additionalProperties must be a boolean")
        for name, child in properties.items():
            if not isinstance(name, str) or not name or len(name) > 100:
                raise AgentDefinitionError(field_name + " property names are invalid")
            validate_bounded_schema(child, field_name + "." + name, depth=depth + 1)
    elif schema_type == "array":
        if "items" not in schema:
            raise AgentDefinitionError(field_name + " array schemas must declare items")
        validate_bounded_schema(schema["items"], field_name + ".items", depth=depth + 1)


@dataclass(frozen=True, slots=True)
class AgentBudgets:
    """Hard execution ceilings; every allocatable resource is bounded."""

    max_iterations: int = 12
    deadline_seconds: int = 300
    max_tool_calls: int = 20
    max_model_tokens: int = 20000
    max_input_bytes: int = MAX_INPUT_BYTES
    max_output_bytes: int = MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        for name, value, maximum, minimum in (
            ("max_iterations", self.max_iterations, 1000, 1),
            ("deadline_seconds", self.deadline_seconds, 3600, 1),
            ("max_tool_calls", self.max_tool_calls, 1000, 0),
            ("max_input_bytes", self.max_input_bytes, 1024 * 1024, 1),
            ("max_output_bytes", self.max_output_bytes, 1024 * 1024, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise AgentDefinitionError(
                    name + " must be an integer between " + str(minimum) + " and " + str(maximum)
                )
        if isinstance(self.max_model_tokens, bool) or not isinstance(self.max_model_tokens, int) or not 0 <= self.max_model_tokens <= 1000000:
            raise AgentDefinitionError("max_model_tokens must be an integer between 0 and 1000000")


@dataclass(frozen=True, slots=True)
class DataScope:
    """One explicitly named data domain plus scope; never a permission grant."""

    domain: str
    scope_type: str
    scope_id: str
    owner_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.domain, str) or self.domain not in _ALLOWED_DATA_DOMAINS:
            raise AgentDefinitionError("domain must be one of conversation, knowledge, memory")
        object.__setattr__(self, "scope_type", _required_identifier(self.scope_type, "scope_type", maximum=40))
        object.__setattr__(self, "scope_id", _required_identifier(self.scope_id, "scope_id"))
        object.__setattr__(self, "owner_id", _required_identifier(self.owner_id, "owner_id"))


@dataclass(frozen=True, slots=True)
class CompletionCriteria:
    """Bounded, human-auditable completion conditions for a run."""

    kind: str
    description: str
    min_results: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _ALLOWED_COMPLETION_KINDS:
            raise AgentDefinitionError("completion kind is not supported")
        object.__setattr__(self, "description", _required_text(self.description, "completion description", maximum=500))
        if isinstance(self.min_results, bool) or not isinstance(self.min_results, int) or not 0 <= self.min_results <= 1000:
            raise AgentDefinitionError("min_results must be an integer between 0 and 1000")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Immutable, versioned agent contract. Declares, never grants, capability."""

    agent_id: str
    version: str
    goal: str
    description: str
    input_schema: dict
    output_schema: dict
    completion: CompletionCriteria
    budgets: AgentBudgets = field(default_factory=AgentBudgets)
    allowed_tools: tuple = ()
    allowed_models: tuple = ()
    data_scopes: tuple = ()
    approval_policy: str = "explicit"
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not AGENT_ID_PATTERN.fullmatch(self.agent_id):
            raise AgentDefinitionError("agent_id must be a stable lowercase identifier")
        if not isinstance(self.version, str) or not SEMVER_PATTERN.fullmatch(self.version):
            raise AgentDefinitionError("agent version must use semantic version format")
        object.__setattr__(self, "goal", _required_text(self.goal, "goal", maximum=500))
        object.__setattr__(self, "description", _required_text(self.description, "description", maximum=2000))
        _bounded_json(self.input_schema, "input_schema", maximum=MAX_SCHEMA_BYTES)
        _bounded_json(self.output_schema, "output_schema", maximum=MAX_SCHEMA_BYTES)
        validate_bounded_schema(self.input_schema, "input_schema")
        validate_bounded_schema(self.output_schema, "output_schema")
        if not isinstance(self.completion, CompletionCriteria):
            raise AgentDefinitionError("completion must be a CompletionCriteria")
        if not isinstance(self.budgets, AgentBudgets):
            raise AgentDefinitionError("budgets must be an AgentBudgets")
        if not isinstance(self.allowed_tools, tuple) or any(not isinstance(item, str) for item in self.allowed_tools):
            raise AgentDefinitionError("allowed_tools must be a tuple of strings")
        if len(self.allowed_tools) > 50 or any(not AGENT_ID_PATTERN.fullmatch(item) for item in self.allowed_tools):
            raise AgentDefinitionError("allowed_tools must contain valid tool identifiers")
        if not isinstance(self.allowed_models, tuple) or len(self.allowed_models) > 50:
            raise AgentDefinitionError("allowed_models must be a bounded tuple")
        for item in self.allowed_models:
            _required_identifier(item, "model identifier", maximum=160)
        if not isinstance(self.data_scopes, tuple) or any(not isinstance(item, str) for item in self.data_scopes):
            raise AgentDefinitionError("data_scopes must be a tuple of domain names")
        for item in self.data_scopes:
            if item not in _ALLOWED_DATA_DOMAINS:
                raise AgentDefinitionError("data domain declarations are unsupported")
        if self.approval_policy not in _ALLOWED_APPROVAL_POLICIES:
            raise AgentDefinitionError("approval_policy must be explicit; agents cannot self-approve")
        if not isinstance(self.enabled, bool):
            raise AgentDefinitionError("enabled must be a boolean")


@dataclass(frozen=True, slots=True)
class AgentTask:
    """A goal with explicit owner and data scopes; tasks never grant permissions."""

    task_id: str
    agent_id: str
    agent_version: str
    owner_id: str
    title: str
    payload: dict
    data_scopes: tuple = ()
    status: TaskStatus = TaskStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not HEX32_PATTERN.fullmatch(self.task_id):
            raise ValueError("task_id must be a 32-character lowercase hex identifier")
        if not isinstance(self.agent_id, str) or not AGENT_ID_PATTERN.fullmatch(self.agent_id):
            raise ValueError("agent_id is invalid")
        if not isinstance(self.agent_version, str) or not SEMVER_PATTERN.fullmatch(self.agent_version):
            raise ValueError("agent_version is invalid")
        object.__setattr__(self, "owner_id", _required_identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "title", _required_text(self.title, "task title", maximum=200))
        _bounded_json(self.payload, "task payload", maximum=MAX_INPUT_BYTES)
        if not isinstance(self.data_scopes, tuple) or len(self.data_scopes) > 10:
            raise ValueError("data_scopes must be a tuple of at most 10 explicit scopes")
        for scope in self.data_scopes:
            if not isinstance(scope, DataScope):
                raise ValueError("each data scope must be a DataScope")
            if scope.owner_id != self.owner_id:
                raise ValueError("task scopes must belong to the task owner")
        if not isinstance(self.status, TaskStatus):
            raise ValueError("status must be a TaskStatus")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Persistent run state; version is the optimistic concurrency token."""

    run_id: str
    task_id: str
    agent_id: str
    agent_version: str
    owner_id: str
    trace_id: str
    status: AgentRunStatus
    scope_type: str
    scope_id: str
    version: int = 1
    attempt: int = 1
    iteration: int = 0
    tool_calls: int = 0
    model_tokens: int = 0
    last_checkpoint_sequence: int = 0
    pending_approval_id: str | None = None
    stop_reason: StopReason | None = None
    error_code: str | None = None
    error_message: str | None = None
    outcome: dict | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not HEX32_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must be a 32-character lowercase hex identifier")
        if not isinstance(self.task_id, str) or not HEX32_PATTERN.fullmatch(self.task_id):
            raise ValueError("task_id must be a 32-character lowercase hex identifier")
        if not isinstance(self.agent_id, str) or not AGENT_ID_PATTERN.fullmatch(self.agent_id):
            raise ValueError("agent_id is invalid")
        if not isinstance(self.agent_version, str) or not SEMVER_PATTERN.fullmatch(self.agent_version):
            raise ValueError("agent_version is invalid")
        object.__setattr__(self, "owner_id", _required_identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "trace_id", _required_identifier(self.trace_id, "trace_id", maximum=80))
        object.__setattr__(self, "scope_type", _required_identifier(self.scope_type, "scope_type", maximum=40))
        object.__setattr__(self, "scope_id", _required_identifier(self.scope_id, "scope_id"))
        if not isinstance(self.status, AgentRunStatus):
            raise ValueError("status must be an AgentRunStatus")
        for name, value in (
            ("version", self.version), ("attempt", self.attempt), ("iteration", self.iteration),
            ("tool_calls", self.tool_calls), ("model_tokens", self.model_tokens),
            ("last_checkpoint_sequence", self.last_checkpoint_sequence),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(name + " must be a non-negative integer")
        if self.pending_approval_id is not None and (
            not isinstance(self.pending_approval_id, str) or not self.pending_approval_id.strip() or len(self.pending_approval_id) > 80
        ):
            raise ValueError("pending_approval_id is invalid")
        if self.stop_reason is not None and not isinstance(self.stop_reason, StopReason):
            raise ValueError("stop_reason must be a StopReason")
        for name, value in (("error_code", self.error_code), ("error_message", self.error_message)):
            if value is not None and (not isinstance(value, str) or len(value) > 300):
                raise ValueError(name + " is invalid or too long")
        if self.outcome is not None:
            _bounded_json(self.outcome, "outcome", maximum=MAX_OUTPUT_BYTES)
        for name, value in (
            ("created_at", self.created_at), ("started_at", self.started_at),
            ("updated_at", self.updated_at), ("finished_at", self.finished_at),
        ):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
                raise ValueError(name + " must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AgentStep:
    """One audited plan/act/observe/evaluate step of a run."""

    step_id: str
    run_id: str
    ordinal: int
    kind: StepKind
    status: StepStatus
    summary: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not HEX32_PATTERN.fullmatch(self.step_id):
            raise ValueError("step_id must be a 32-character lowercase hex identifier")
        if not isinstance(self.run_id, str) or not HEX32_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must be a 32-character lowercase hex identifier")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        if not isinstance(self.kind, StepKind) or not isinstance(self.status, StepStatus):
            raise ValueError("step kind and status must use their enums")
        object.__setattr__(self, "summary", _required_text(self.summary, "step summary", maximum=500))
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        _bounded_json(self.data, "step data", maximum=4096)


@dataclass(frozen=True, slots=True)
class AgentCheckpoint:
    """Versioned JSON checkpoint; payloads are bounded and never contain secrets."""

    checkpoint_id: str
    run_id: str
    sequence: int
    schema_version: int
    payload: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint_id, str) or not HEX32_PATTERN.fullmatch(self.checkpoint_id):
            raise ValueError("checkpoint_id must be a 32-character lowercase hex identifier")
        if not isinstance(self.run_id, str) or not HEX32_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must be a 32-character lowercase hex identifier")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version != 1:
            raise ValueError("checkpoint schema_version must be 1")
        _bounded_json(self.payload, "checkpoint payload", maximum=MAX_CHECKPOINT_BYTES)
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RunEvent:
    """Append-only, redacted run event for audit and safe API summaries."""

    event_id: str
    run_id: str
    event_type: str
    ordinal: int
    outcome: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not HEX32_PATTERN.fullmatch(self.event_id):
            raise ValueError("event_id must be a 32-character lowercase hex identifier")
        if not isinstance(self.run_id, str) or not HEX32_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must be a 32-character lowercase hex identifier")
        object.__setattr__(self, "event_type", _required_text(self.event_type, "event_type", maximum=80))
        object.__setattr__(self, "outcome", _required_text(self.outcome, "event outcome", maximum=40))
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        _bounded_json(self.metadata, "event metadata", maximum=4096)
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


def new_task_id() -> str:
    return uuid4().hex


def new_run_id() -> str:
    return uuid4().hex
