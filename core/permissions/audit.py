"""Redacted, append-only permission and tool audit service."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.repositories.audit_repository import AuditRepository
from .types import PermissionOperation, PermissionResource, PermissionSubject


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    request_id: str
    outcome: str
    created_at: datetime
    subject: PermissionSubject | None = None
    resource: PermissionResource | None = None
    operation: PermissionOperation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditPersistenceError(RuntimeError):
    """A required audit event could not be durably recorded."""


class AuditService:
    """Persists structured events while allowing only explicitly safe metadata."""

    SAFE_METADATA_KEYS = {
        "tool_id",
        "tool_version",
        "grant_id",
        "approval_id",
        "reason_code",
        "decision",
        "status",
        "risk_class",
        "handler_category",
        "exception_type",
        "duration_ms",
        "timeout_ms",
        "input_bytes",
        "output_bytes",
        "size_bytes",
        "count",
        "provider_id",
        "runtime_id",
        "model_id",
        "destination_type",
        "policy_version",
    }
    _SECRET_PATTERNS = (
        re.compile(r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)\b"),
        re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    )

    def __init__(self, repository: AuditRepository, *, clock=None) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def _redact_metadata(cls, metadata: dict[str, Any] | None) -> dict[str, Any]:
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise ValueError("Audit metadata must be a JSON object.")

        safe: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str) or key not in cls.SAFE_METADATA_KEYS:
                continue
            if isinstance(value, str):
                if any(pattern.search(value) for pattern in cls._SECRET_PATTERNS):
                    safe[key] = "[REDACTED]"
                else:
                    safe[key] = value[:256]
            elif isinstance(value, (int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, (list, tuple)):
                safe[key] = [
                    item[:128] if isinstance(item, str) and not any(
                        pattern.search(item) for pattern in cls._SECRET_PATTERNS
                    ) else "[REDACTED]" if isinstance(item, str) else item
                    for item in value[:20]
                    if isinstance(item, (str, int, float, bool)) or item is None
                ]
        return safe

    def record(
        self,
        *,
        event_type: str,
        request_id: str,
        outcome: str,
        subject: PermissionSubject | None = None,
        resource: PermissionResource | None = None,
        operation: PermissionOperation | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        for name, value, maximum in (
            ("event_type", event_type, 80),
            ("request_id", request_id, 80),
            ("outcome", outcome, 40),
        ):
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                raise ValueError(f"{name} must contain 1..{maximum} characters")
        if subject is not None and not isinstance(subject, PermissionSubject):
            raise TypeError("subject must be a PermissionSubject")
        if resource is not None and not isinstance(resource, PermissionResource):
            raise TypeError("resource must be a PermissionResource")
        if operation is not None and not isinstance(operation, PermissionOperation):
            raise TypeError("operation must be a PermissionOperation")

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("Audit clock must return a timezone-aware datetime.")
        event = AuditEvent(
            event_id=str(uuid4()),
            event_type=event_type.strip(),
            request_id=request_id.strip(),
            outcome=outcome.strip(),
            created_at=now,
            subject=subject,
            resource=resource,
            operation=operation,
            metadata=self._redact_metadata(metadata),
        )
        try:
            self.repository.append(event)
        except Exception as exc:
            raise AuditPersistenceError("Audit event could not be persisted.") from exc
        return event
