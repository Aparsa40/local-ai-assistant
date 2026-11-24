"""Persistence adapter for scoped memory records."""
from __future__ import annotations

from datetime import datetime

from core.database import MemoryRecord, utcnow_naive
from .base import BaseRepository


class MemoryRepository(BaseRepository):
    """Owns all ORM access and transaction boundaries for memory records."""

    def get(self, memory_id: int, scope_type: str, scope_id: str, owner_id: str):
        return (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.id == memory_id,
                MemoryRecord.scope_type == scope_type,
                MemoryRecord.scope_id == scope_id,
                MemoryRecord.owner_id == owner_id,
                MemoryRecord.status != "deleted",
            )
            .first()
        )

    def list_scope(self, scope_type: str, scope_id: str, owner_id: str, statuses: tuple[str, ...], now: datetime):
        return (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.scope_type == scope_type,
                MemoryRecord.scope_id == scope_id,
                MemoryRecord.owner_id == owner_id,
                MemoryRecord.status.in_(statuses),
                or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now),
            )
            .order_by(MemoryRecord.updated_at.desc(), MemoryRecord.id.desc())
            .all()
        )

    def find_duplicate(self, memory_type: str, scope_type: str, scope_id: str, owner_id: str, normalized_content: str):
        records = self.list_scope(scope_type, scope_id, owner_id, ("candidate", "active"), utcnow_naive())
        return next(
            (
                record for record in records
                if record.memory_type == memory_type
                and " ".join(record.content.casefold().split()) == normalized_content
            ),
            None,
        )

    def find_dedup_key(self, dedup_key: str, scope_type: str, scope_id: str, owner_id: str):
        return (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.dedup_key == dedup_key,
                MemoryRecord.scope_type == scope_type,
                MemoryRecord.scope_id == scope_id,
                MemoryRecord.owner_id == owner_id,
                MemoryRecord.status.in_(("candidate", "active")),
            )
            .order_by(MemoryRecord.id.desc())
            .first()
        )

    def add(self, record: MemoryRecord) -> MemoryRecord:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def save(self, record: MemoryRecord) -> MemoryRecord:
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete(self, record: MemoryRecord) -> None:
        self.db.delete(record)
        self.db.commit()

    def expire_due(self, scope_type: str, scope_id: str, owner_id: str, now: datetime) -> int:
        records = (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.scope_type == scope_type,
                MemoryRecord.scope_id == scope_id,
                MemoryRecord.owner_id == owner_id,
                MemoryRecord.status.in_(("candidate", "active")),
                MemoryRecord.expires_at.is_not(None),
                MemoryRecord.expires_at <= now,
            )
            .all()
        )
        for record in records:
            record.status = "expired"
            record.updated_at = now
        if records:
            self.db.commit()
        return len(records)

    def touch(self, record: MemoryRecord, now: datetime) -> MemoryRecord:
        record.last_accessed_at = now
        return self.save(record)
