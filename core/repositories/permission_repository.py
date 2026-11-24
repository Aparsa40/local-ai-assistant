"""Persistence adapter for exact-scope permission grants."""
from __future__ import annotations

from datetime import datetime, timezone

from core.database import PermissionGrantRecord, to_utc_naive
from core.permissions.types import (
    PermissionGrant,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from .base import BaseRepository


class PermissionRepository(BaseRepository):
    """Owns ORM access and transaction boundaries for permission grants."""

    @staticmethod
    def _to_contract(record: PermissionGrantRecord) -> PermissionGrant:
        def aware(value):
            if value is None:
                return None
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

        return PermissionGrant(
            grant_id=record.grant_id,
            subject=PermissionSubject(SubjectType(record.subject_type), record.subject_id),
            resource=PermissionResource(ResourceType(record.resource_type), record.resource_id),
            operation=PermissionOperation(record.operation),
            scope=PermissionScope(ScopeType(record.scope_type), record.scope_id, record.owner_id),
            issued_by=record.issued_by,
            created_at=aware(record.created_at),
            expires_at=aware(record.expires_at),
            revoked_at=aware(record.revoked_at),
        )

    def create(self, grant: PermissionGrant) -> PermissionGrant:
        record = PermissionGrantRecord(
            grant_id=grant.grant_id,
            subject_type=grant.subject.subject_type.value,
            subject_id=grant.subject.subject_id,
            resource_type=grant.resource.resource_type.value,
            resource_id=grant.resource.resource_id,
            operation=grant.operation.value,
            scope_type=grant.scope.scope_type.value,
            scope_id=grant.scope.scope_id,
            owner_id=grant.scope.owner_id,
            issued_by=grant.issued_by,
            created_at=to_utc_naive(grant.created_at),
            expires_at=to_utc_naive(grant.expires_at) if grant.expires_at else None,
            revoked_at=to_utc_naive(grant.revoked_at) if grant.revoked_at else None,
            conditions={},
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def get(self, grant_id: str) -> PermissionGrant | None:
        record = self.db.query(PermissionGrantRecord).filter(
            PermissionGrantRecord.grant_id == grant_id
        ).first()
        return self._to_contract(record) if record else None

    def list_exact(self, subject, resource, operation, scope) -> tuple[PermissionGrant, ...]:
        records = (
            self.db.query(PermissionGrantRecord)
            .filter(
                PermissionGrantRecord.subject_type == subject.subject_type.value,
                PermissionGrantRecord.subject_id == subject.subject_id,
                PermissionGrantRecord.resource_type == resource.resource_type.value,
                PermissionGrantRecord.resource_id == resource.resource_id,
                PermissionGrantRecord.operation == operation.value,
                PermissionGrantRecord.scope_type == scope.scope_type.value,
                PermissionGrantRecord.scope_id == scope.scope_id,
                PermissionGrantRecord.owner_id == scope.owner_id,
            )
            .order_by(PermissionGrantRecord.created_at.desc(), PermissionGrantRecord.grant_id)
            .all()
        )
        return tuple(self._to_contract(record) for record in records)

    def revoke(self, grant_id: str, *, revoked_at: datetime) -> PermissionGrant | None:
        record = self.db.query(PermissionGrantRecord).filter(
            PermissionGrantRecord.grant_id == grant_id
        ).first()
        if record is None:
            return None
        if record.revoked_at is None:
            record.revoked_at = to_utc_naive(revoked_at)
            self.db.commit()
            self.db.refresh(record)
        return self._to_contract(record)
