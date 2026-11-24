"""Typed, validated contracts for application-owned authorization.

These values describe an authorization request or result. They do not grant
permissions by themselves; only PermissionManager policy evaluation may do so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from uuid import uuid4


class SubjectType(str, Enum):
    USER = "user"
    SERVICE = "service"
    AGENT_TYPE = "agent_type"
    AGENT_RUN = "agent_run"


class ResourceType(str, Enum):
    CONVERSATION = "conversation"
    MEMORY_SCOPE = "memory_scope"
    PROFILE = "profile"
    TOOL = "tool"
    KNOWLEDGE_SOURCE = "knowledge_source"
    FILE = "file"
    CONNECTOR = "connector"
    PROVIDER_CREDENTIAL = "provider_credential"


class PermissionOperation(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    PUBLISH = "publish"
    TRANSMIT = "transmit"
    APPROVE = "approve"
    ADMINISTER = "administer"


class ScopeType(str, Enum):
    LOCAL = "local"
    USER = "user"
    CONVERSATION = "conversation"
    TASK = "task"
    PROJECT = "project"
    FOLDER = "folder"
    PROVIDER = "provider"
    GLOBAL = "global"


class DecisionEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class DataSensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SECRET = "secret"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


def _required_identifier(value: str, field_name: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must contain 1..{maximum} characters")
    if normalized in {"*", "**", "all", "any"}:
        raise ValueError(f"{field_name} cannot use wildcard identifiers")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class PermissionSubject:
    subject_type: SubjectType
    subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject_type, SubjectType):
            raise ValueError("subject_type must be a SubjectType")
        object.__setattr__(self, "subject_id", _required_identifier(self.subject_id, "subject_id"))


@dataclass(frozen=True, slots=True)
class PermissionResource:
    resource_type: ResourceType
    resource_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.resource_type, ResourceType):
            raise ValueError("resource_type must be a ResourceType")
        object.__setattr__(self, "resource_id", _required_identifier(self.resource_id, "resource_id", maximum=255))


@dataclass(frozen=True, slots=True)
class PermissionScope:
    scope_type: ScopeType
    scope_id: str
    owner_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope_type, ScopeType):
            raise ValueError("scope_type must be a ScopeType")
        object.__setattr__(self, "scope_id", _required_identifier(self.scope_id, "scope_id"))
        object.__setattr__(self, "owner_id", _required_identifier(self.owner_id, "owner_id"))


@dataclass(frozen=True, slots=True)
class AccessRequest:
    subject: PermissionSubject
    resource: PermissionResource
    operation: PermissionOperation
    scope: PermissionScope
    request_id: str = field(default_factory=lambda: str(uuid4()))
    sensitivity: DataSensitivity = DataSensitivity.PRIVATE
    destination: str | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.subject, PermissionSubject):
            raise ValueError("subject must be a PermissionSubject")
        if not isinstance(self.resource, PermissionResource):
            raise ValueError("resource must be a PermissionResource")
        if not isinstance(self.operation, PermissionOperation):
            raise ValueError("operation must be a PermissionOperation")
        if not isinstance(self.scope, PermissionScope):
            raise ValueError("scope must be a PermissionScope")
        object.__setattr__(self, "request_id", _required_identifier(self.request_id, "request_id", maximum=80))
        if not isinstance(self.sensitivity, DataSensitivity):
            raise ValueError("sensitivity must be a DataSensitivity")
        if self.destination is not None:
            object.__setattr__(self, "destination", _required_identifier(self.destination, "destination", maximum=255))
        if not isinstance(self.requested_at, datetime) or self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    effect: DecisionEffect
    reason_code: str
    request_id: str
    grant_id: str | None = None
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.effect, DecisionEffect):
            raise ValueError("effect must be a DecisionEffect")
        object.__setattr__(self, "reason_code", _required_identifier(self.reason_code, "reason_code", maximum=80))
        object.__setattr__(self, "request_id", _required_identifier(self.request_id, "request_id", maximum=80))
        if self.grant_id is not None:
            object.__setattr__(self, "grant_id", _required_identifier(self.grant_id, "grant_id", maximum=80))
        if not isinstance(self.decided_at, datetime) or self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    grant_id: str
    subject: PermissionSubject
    resource: PermissionResource
    operation: PermissionOperation
    scope: PermissionScope
    issued_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    requires_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _required_identifier(self.grant_id, "grant_id", maximum=80))
        object.__setattr__(self, "issued_by", _required_identifier(self.issued_by, "issued_by"))
        if not isinstance(self.subject, PermissionSubject):
            raise ValueError("subject must be a PermissionSubject")
        if not isinstance(self.resource, PermissionResource):
            raise ValueError("resource must be a PermissionResource")
        if not isinstance(self.operation, PermissionOperation):
            raise ValueError("operation must be a PermissionOperation")
        if not isinstance(self.scope, PermissionScope):
            raise ValueError("scope must be a PermissionScope")
        for name, value in (("created_at", self.created_at), ("expires_at", self.expires_at), ("revoked_at", self.revoked_at)):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
                raise ValueError(f"{name} must be timezone-aware")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("revoked_at cannot be earlier than created_at")
        if not isinstance(self.requires_approval, bool):
            raise ValueError("requires_approval must be a boolean")

    def is_active(self, at: datetime) -> bool:
        """Return whether the grant is active at a timezone-aware instant."""
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError("at must be timezone-aware")
        return (
            self.created_at <= at
            and (self.expires_at is None or at < self.expires_at)
            and (self.revoked_at is None or at < self.revoked_at)
        )



@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    request_id: str
    action_hash: str
    subject: PermissionSubject
    resource: PermissionResource
    operation: PermissionOperation
    scope: PermissionScope
    requested_by: str
    created_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str | None = None
    decided_at: datetime | None = None
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", _required_identifier(self.approval_id, "approval_id", maximum=80))
        object.__setattr__(self, "request_id", _required_identifier(self.request_id, "request_id", maximum=80))
        object.__setattr__(self, "requested_by", _required_identifier(self.requested_by, "requested_by"))
        if not isinstance(self.action_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", self.action_hash):
            raise ValueError("action_hash must be a lowercase SHA-256 hex digest")
        if not isinstance(self.subject, PermissionSubject):
            raise ValueError("subject must be a PermissionSubject")
        if not isinstance(self.resource, PermissionResource):
            raise ValueError("resource must be a PermissionResource")
        if not isinstance(self.operation, PermissionOperation):
            raise ValueError("operation must be a PermissionOperation")
        if not isinstance(self.scope, PermissionScope):
            raise ValueError("scope must be a PermissionScope")
        if not isinstance(self.status, ApprovalStatus):
            raise ValueError("status must be an ApprovalStatus")
        for name, value in (
            ("created_at", self.created_at),
            ("expires_at", self.expires_at),
            ("decided_at", self.decided_at),
            ("consumed_at", self.consumed_at),
        ):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
                raise ValueError(f"{name} must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if (self.decided_by is None) != (self.decided_at is None):
            raise ValueError("decided_by and decided_at must be set together")



@dataclass(frozen=True, slots=True)
class AccessContext:
    """Explicit trusted application identity and scope for one service request."""

    subject: PermissionSubject
    scope: PermissionScope
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.subject, PermissionSubject):
            raise ValueError("subject must be a PermissionSubject")
        if not isinstance(self.scope, PermissionScope):
            raise ValueError("scope must be a PermissionScope")
        object.__setattr__(self, "request_id", _required_identifier(self.request_id, "request_id", maximum=80))

    def build_request(
        self,
        resource: PermissionResource,
        operation: PermissionOperation,
    ) -> AccessRequest:
        return AccessRequest(
            subject=self.subject,
            resource=resource,
            operation=operation,
            scope=self.scope,
            request_id=self.request_id,
        )
