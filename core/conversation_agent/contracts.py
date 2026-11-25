"""Versioned, validated contracts for the Phase 8 Conversation Agent.

These are pure application-side contracts. They never invoke models, never
execute tools, and never grant permissions. Model output and client payloads
treated here are untrusted input that must be validated by application code.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

CONVERSATION_AGENT_CONTRACTS_VERSION = 1
EVENT_PROTOCOL_VERSION = 1

MAX_MESSAGE_CHARS = 12000
MAX_SOURCE_REFS = 100
MAX_LIMITATION_CHARS = 500
MAX_LIMITATIONS = 20
MAX_METADATA_ENTRIES = 20
MAX_METADATA_VALUE_CHARS = 300

_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,80}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z0-9_]+$")

EVENT_TYPES = frozenset({
    "accepted", "status", "progress", "candidate", "validation",
    "approval_required", "final", "error", "cancelled",
})


class ContractValidationError(ValueError):
    """A contract payload failed application-side validation."""


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


def _check_code(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _CODE_PATTERN.fullmatch(value):
        raise ContractValidationError(label + " must be a lowercase reason code")
    return value


def _safe_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(label + " must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ContractValidationError(label + " is empty or exceeds the bound")
    if any(ord(ch) < 32 for ch in normalized):
        raise ContractValidationError(label + " must not contain control characters")
    return normalized


def _safe_metadata(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_METADATA_ENTRIES:
        raise ContractValidationError("metadata must be a bounded mapping")
    safe: dict = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise ContractValidationError("metadata keys must be bounded strings")
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and len(item) > MAX_METADATA_VALUE_CHARS:
                raise ContractValidationError("metadata string values exceed the bound")
            safe[key] = item
        else:
            raise ContractValidationError("metadata values must be primitives")
    return safe


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Route(str, Enum):
    """Closed dispatch route enum; deterministic dispatch may only emit these."""

    DIRECT_RESPONSE = "direct_response"
    DETERMINISTIC_WORKFLOW = "deterministic_workflow"
    AGENT_DELEGATION = "agent_delegation"
    NEEDS_USER_INPUT = "needs_user_input"
    BLOCKED = "blocked"


class DestinationClass(str, Enum):
    NONE = "none"
    LOCAL = "local"
    CLOUD = "cloud"


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    NEEDS_INPUT = "needs_input"
    UNAVAILABLE = "unavailable"


class ExecutionMode(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DELEGATED = "delegated"
    DETERMINISTIC = "deterministic"
    NONE = "none"


class ValidationState(str, Enum):
    VALID = "valid"
    PARTIAL = "partial"
    REJECTED = "rejected"


@dataclass(frozen=True)
class DataScopeRef:
    """Explicit data scope reference; converted to the runtime DataScope type."""

    domain: str
    scope_type: str
    scope_id: str
    owner_id: str

    def validate(self) -> None:
        for label, value in (
            ("domain", self.domain), ("scope_type", self.scope_type),
            ("scope_id", self.scope_id), ("owner_id", self.owner_id),
        ):
            _safe_text(value, label, 160)
        if self.domain not in {"conversation", "knowledge", "memory"}:
            raise ContractValidationError("data scope domain is not supported")

    def to_dict(self) -> dict:
        return {
            "domain": self.domain, "scope_type": self.scope_type,
            "scope_id": self.scope_id, "owner_id": self.owner_id,
        }


@dataclass(frozen=True)
class ExecutionBudget:
    """Bounded execution limits enforced by the conversation service."""

    wall_clock_seconds: int = 300
    max_output_chars: int = 40000

    def validate(self) -> None:
        if isinstance(self.wall_clock_seconds, bool) or not isinstance(self.wall_clock_seconds, int):
            raise ContractValidationError("wall_clock_seconds must be an integer")
        if not 5 <= self.wall_clock_seconds <= 3600:
            raise ContractValidationError("wall_clock_seconds is outside the bounded range")
        if isinstance(self.max_output_chars, bool) or not isinstance(self.max_output_chars, int):
            raise ContractValidationError("max_output_chars must be an integer")
        if not 200 <= self.max_output_chars <= 200000:
            raise ContractValidationError("max_output_chars is outside the bounded range")


@dataclass(frozen=True)
class ConversationRequest:
    """Validated user-turn intake contract (WP-8.1)."""

    session_id: int
    message: str
    request_id: str
    schema_version: int = CONVERSATION_AGENT_CONTRACTS_VERSION
    provider_id: str | None = None
    model: str | None = None
    authorize_private_context_egress: bool = False
    force_delegation: bool = False
    history_limit: int = 20
    memory_scopes: tuple[DataScopeRef, ...] = ()
    knowledge_scopes: tuple[DataScopeRef, ...] = ()
    client_metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    @property
    def budget(self) -> ExecutionBudget:
        return ExecutionBudget()

    def validate(self) -> None:
        if isinstance(self.session_id, bool) or not isinstance(self.session_id, int) or self.session_id < 1:
            raise ContractValidationError("session_id must be a positive integer")
        message = self.message if isinstance(self.message, str) else ""
        if not message.strip():
            raise ContractValidationError("message must not be empty")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ContractValidationError("message exceeds the 12000 character bound")
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in message):
            raise ContractValidationError("message must not contain control characters")
        if not isinstance(self.request_id, str) or not _REQUEST_ID_PATTERN.fullmatch(self.request_id):
            raise ContractValidationError("request_id must be a stable bounded identifier")
        if self.provider_id is not None:
            if not isinstance(self.provider_id, str) or not _PROVIDER_PATTERN.fullmatch(self.provider_id):
                raise ContractValidationError("provider_id must be a provider identifier")
        if self.model not in (None, ""):
            _safe_text(self.model, "model", 160)
        self._bounded_int(self.history_limit, "history_limit", 1, 100)
        if not isinstance(self.authorize_private_context_egress, bool) or not isinstance(self.force_delegation, bool):
            raise ContractValidationError("boolean flags must be booleans")
        if self.schema_version != CONVERSATION_AGENT_CONTRACTS_VERSION:
            raise ContractValidationError("unsupported contract schema version")
        for scope in self.memory_scopes + self.knowledge_scopes:
            scope.validate()
        _safe_metadata(self.client_metadata)
        self.budget.validate()

    @staticmethod
    def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ContractValidationError(label + " is outside the bounded range")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, session_id: int) -> "ConversationRequest":
        if not isinstance(payload, dict):
            raise ContractValidationError("request payload must be an object")
        request = cls(
            session_id=session_id,
            message=payload.get("message", ""),
            request_id=payload.get("request_id") or new_request_id(),
            schema_version=payload.get("schema_version", CONVERSATION_AGENT_CONTRACTS_VERSION),
            provider_id=payload.get("provider_id"),
            model=payload.get("model"),
            authorize_private_context_egress=payload.get("authorize_private_context_egress", False),
            force_delegation=payload.get("force_delegation", False),
            history_limit=payload.get("history_limit", 20),
            memory_scopes=cls._scopes(payload.get("memory_scopes")),
            knowledge_scopes=cls._scopes(payload.get("knowledge_scopes")),
            client_metadata=payload.get("client_metadata") or {},
        )
        request.validate()
        return request

    @staticmethod
    def _scopes(value: Any) -> tuple[DataScopeRef, ...]:
        if value in (None, ()):
            return ()
        if not isinstance(value, list) or len(value) > 10:
            raise ContractValidationError("scopes must be a list of at most 10 entries")
        refs = []
        for item in value:
            if not isinstance(item, dict):
                raise ContractValidationError("each scope entry must be an object")
            refs.append(DataScopeRef(**item))
        return tuple(refs)


@dataclass(frozen=True)
class DispatchDecision:
    """Deterministic dispatch outcome (WP-8.2); never carries permission authority."""

    route: Route
    reason_codes: tuple[str, ...]
    destination_class: DestinationClass = DestinationClass.NONE
    provider_id: str | None = None
    model: str | None = None
    requires_approval: bool = False
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)

    def __post_init__(self) -> None:
        if not isinstance(self.route, Route):
            raise ContractValidationError("route must be a Route value")
        if not self.reason_codes:
            raise ContractValidationError("dispatch must record at least one reason code")
        for code in self.reason_codes:
            _check_code(code, "reason code")
        if not isinstance(self.destination_class, DestinationClass):
            raise ContractValidationError("destination_class must be a DestinationClass value")
        self.budget.validate()

    def to_dict(self) -> dict:
        return {
            "route": self.route.value,
            "reason_codes": list(self.reason_codes),
            "destination_class": self.destination_class.value,
            "provider_id": self.provider_id,
            "model": self.model,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True)
class Provenance:
    """Safe provenance metadata; never carries prompts, secrets or reasoning."""

    session_id: int
    request_id: str
    route: str
    mode: str
    provider_id: str | None
    model_used: str | None
    fallback_applied: bool = False
    fallback_reason: str | None = None
    execution_status: str | None = None
    orchestration_goal_id: str | None = None
    orchestration_plan_id: str | None = None
    source_refs: tuple[str, ...] = ()
    error_code: str | None = None
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        for ref in self.source_refs:
            if not isinstance(ref, str) or not ref or len(ref) > 300:
                raise ContractValidationError("source references must be bounded strings")
        if len(self.source_refs) > MAX_SOURCE_REFS:
            raise ContractValidationError("too many source references")
        if self.error_code is not None:
            _check_code(self.error_code, "error code")

    def to_dict(self) -> dict:
        return {
            "contracts_version": CONVERSATION_AGENT_CONTRACTS_VERSION,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "route": self.route,
            "mode": self.mode,
            "provider_id": self.provider_id,
            "model_used": self.model_used,
            "fallback_applied": self.fallback_applied,
            "fallback_reason": self.fallback_reason,
            "execution_status": self.execution_status,
            "orchestration_goal_id": self.orchestration_goal_id,
            "orchestration_plan_id": self.orchestration_plan_id,
            "source_refs": list(self.source_refs)[:MAX_SOURCE_REFS],
            "error_code": self.error_code,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ResponseCandidate:
    """Normalized execution outcome shared by every strategy (WP-8.3/8.4)."""

    content: str
    status: ExecutionStatus
    mode: ExecutionMode
    provider_id: str | None = None
    model_used: str | None = None
    fallback_applied: bool = False
    fallback_reason: str | None = None
    source_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    goal_id: str | None = None
    plan_id: str | None = None
    node_outcomes: tuple[dict, ...] = ()
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise ContractValidationError("content must be a string")
        if len(self.content) > 400000:
            raise ContractValidationError("content exceeds the hard output bound")
        if not isinstance(self.status, ExecutionStatus) or not isinstance(self.mode, ExecutionMode):
            raise ContractValidationError("status and mode must be enum values")
        if self.fallback_applied and not self.fallback_reason:
            raise ContractValidationError("a fallback must always be disclosed with a reason")
        for note in self.limitations:
            if not isinstance(note, str) or not note or len(note) > MAX_LIMITATION_CHARS:
                raise ContractValidationError("limitation notes must be bounded strings")
        if len(self.limitations) > MAX_LIMITATIONS:
            raise ContractValidationError("too many limitation notes")
        for ref in self.source_refs:
            if not isinstance(ref, str) or not ref or len(ref) > 300:
                raise ContractValidationError("source references must be bounded strings")
        if self.status is ExecutionStatus.FAILED and not self.error_code:
            raise ContractValidationError("a failed candidate must carry an error code")
        if self.status is ExecutionStatus.COMPLETED and self.error_code:
            raise ContractValidationError("a completed candidate must not carry an error code")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    detail: str

    def __post_init__(self) -> None:
        _check_code(self.code, "issue code")
        if not isinstance(self.detail, str) or not self.detail or len(self.detail) > 300:
            raise ContractValidationError("issue details must be bounded strings")


@dataclass(frozen=True)
class ValidationReport:
    """Application-side validation verdict (WP-8.5)."""

    state: ValidationState
    issues: tuple[ValidationIssue, ...] = ()
    schema_ok: bool = True
    references_ok: bool = True
    coverage_ok: bool = True
    policy_ok: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.state, ValidationState):
            raise ContractValidationError("state must be a ValidationState value")
        if self.state is ValidationState.PARTIAL and not self.issues:
            raise ContractValidationError("a partial validation must record issues")
        if self.state is ValidationState.REJECTED and not self.issues:
            raise ContractValidationError("a rejected validation must record issues")

    @property
    def ok(self) -> bool:
        return self.state is ValidationState.VALID


@dataclass(frozen=True)
class ConversationEvent:
    """One versioned SSE envelope entry; payloads are redacted before emission."""

    event_id: str
    request_id: str
    conversation_id: int
    type: str
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ContractValidationError("event type is not part of the protocol")
        if not isinstance(self.payload, dict):
            raise ContractValidationError("event payload must be a mapping")
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ContractValidationError("event_id must be a stable identifier")

    def to_sse(self) -> str:
        envelope = {
            "v": EVENT_PROTOCOL_VERSION,
            "event_id": self.event_id,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "type": self.type,
            "ts": self.created_at.isoformat(),
            "data": self.payload,
        }
        return "data: " + json.dumps(envelope, ensure_ascii=False, default=str) + "\n\n"


# Safe keys that may be persisted or streamed inside event payloads.
_SAFE_EVENT_KEYS = frozenset({
    "route", "reason_codes", "destination_class", "provider_id", "model",
    "mode", "status", "state", "content", "limitations", "source_refs",
    "fallback_applied", "fallback_reason", "error_code", "message",
    "goal_id", "plan_id", "orchestration_goal_id", "orchestration_plan_id",
    "validation_state", "request_id", "session_id", "issues", "node_outcomes", "detail", "provenance", "deep",
})


def redact_payload(payload: Mapping[str, Any]) -> dict:
    """Keep only whitelisted, bounded keys; never raw context or exceptions."""
    safe: dict = {}
    for key, value in payload.items():
        if key not in _SAFE_EVENT_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > 20000:
                safe[key] = value[:20000]
            else:
                safe[key] = value
        elif isinstance(value, list):
            safe[key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)[:300]
                for item in value[:MAX_SOURCE_REFS]
            ]
        elif isinstance(value, dict):
            safe[key] = redact_payload(value)
    return safe
