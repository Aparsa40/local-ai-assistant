"""Redacted, append-only run event recording for Agent Runtime.

Run events carry safe structural metadata only. Metadata passes through an
explicit whitelist and secret-pattern redaction, mirroring AuditService.
Raw prompts, task payloads, tool outputs, and provider credentials are never
stored in run events.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from core.agents.contracts import RunEvent, _required_text
from core.repositories.run_repository import AgentRunEventRepository


class RunEventPersistenceError(RuntimeError):
    """A run event could not be durably recorded."""


class AgentRunEventRecorder:
    """Records bounded, redacted events for one agent run."""

    SAFE_METADATA_KEYS = {
        "agent_id",
        "agent_version",
        "approval_id",
        "count",
        "decision",
        "detail",
        "domain",
        "duration_ms",
        "error_code",
        "event_kind",
        "grant_id",
        "input_bytes",
        "iteration",
        "kind",
        "limit",
        "model",
        "model_id",
        "output_bytes",
        "provider_id",
        "reason_code",
        "requested_by",
        "scope_id",
        "scope_type",
        "sequence",
        "step",
        "stop_reason",
        "task_id",
        "timeout_ms",
        "tool_calls",
        "tool_id",
        "tool_version",
        "truncated",
    }
    _SECRET_PATTERNS = (
        re.compile(r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)\b"),
        re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    )

    def __init__(self, repository: AgentRunEventRepository, *, clock=None) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def _redact_metadata(cls, metadata) -> dict:
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise ValueError("Run event metadata must be a JSON object.")
        safe: dict = {}
        for key, value in metadata.items():
            if not isinstance(key, str) or key not in cls.SAFE_METADATA_KEYS:
                continue
            if isinstance(value, str):
                if any(pattern.search(value) for pattern in cls._SECRET_PATTERNS):
                    safe[key] = "[REDACTED]"
                else:
                    safe[key] = value[:256]
            elif isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
                safe[key] = value
            elif isinstance(value, (list, tuple)):
                safe[key] = [
                    item[:128] if isinstance(item, str) and not any(
                        pattern.search(item) for pattern in cls._SECRET_PATTERNS
                    ) else "[REDACTED]" if isinstance(item, str) else item
                    for item in list(value)[:20]
                    if isinstance(item, (str, bool, int, float)) or item is None
                ]
        return safe

    def record(
        self,
        *,
        run_id: str,
        event_type: str,
        outcome: str,
        metadata=None,
    ) -> RunEvent:
        event_type = _required_text(event_type, "event_type", maximum=80)
        outcome = _required_text(outcome, "outcome", maximum=40)
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("Run event clock must return a timezone-aware datetime.")
        ordinal = int(now.timestamp() * 1000000)
        event = RunEvent(
            event_id=uuid4().hex,
            run_id=run_id,
            event_type=event_type,
            ordinal=ordinal,
            outcome=outcome,
            metadata=self._redact_metadata(metadata),
            created_at=now,
        )
        try:
            self.repository.append(event)
        except Exception as exc:
            raise RunEventPersistenceError("Run event could not be persisted.") from exc
        return event
