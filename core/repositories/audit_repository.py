"""Append-only persistence adapter for redacted permission audit events."""
from __future__ import annotations

from datetime import datetime, timezone

from core.database import PermissionAuditEventRecord, to_utc_naive
from .base import BaseRepository


class AuditRepository(BaseRepository):
    """Provides append and read operations; deliberately exposes no update/delete."""

    def append(self, event) -> object:
        record = PermissionAuditEventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            request_id=event.request_id,
            subject_type=event.subject.subject_type.value if event.subject else None,
            subject_id=event.subject.subject_id if event.subject else None,
            resource_type=event.resource.resource_type.value if event.resource else None,
            resource_id=event.resource.resource_id if event.resource else None,
            operation=event.operation.value if event.operation else None,
            outcome=event.outcome,
            created_at=to_utc_naive(event.created_at),
            metadata_json=dict(event.metadata),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return event

    def list_for_request(self, request_id: str) -> tuple[dict[str, object], ...]:
        records = (
            self.db.query(PermissionAuditEventRecord)
            .filter(PermissionAuditEventRecord.request_id == request_id)
            .order_by(PermissionAuditEventRecord.created_at, PermissionAuditEventRecord.event_id)
            .all()
        )
        return tuple(
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "request_id": item.request_id,
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "operation": item.operation,
                "outcome": item.outcome,
                "created_at": (
                    item.created_at.replace(tzinfo=timezone.utc)
                    if item.created_at and item.created_at.tzinfo is None
                    else item.created_at
                ),
                "metadata": dict(item.metadata_json or {}),
            }
            for item in records
        )


    def list_recent(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records = (
            self.db.query(PermissionAuditEventRecord)
            .order_by(PermissionAuditEventRecord.created_at.desc(), PermissionAuditEventRecord.event_id)
            .limit(limit)
            .all()
        )
        return tuple(
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "request_id": item.request_id,
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "operation": item.operation,
                "outcome": item.outcome,
                "created_at": (
                    item.created_at.replace(tzinfo=timezone.utc)
                    if item.created_at and item.created_at.tzinfo is None
                    else item.created_at
                ),
                "metadata": dict(item.metadata_json or {}),
            }
            for item in records
        )
