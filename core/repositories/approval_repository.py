"""Persistence adapter for one-time permission approvals."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update

from core.database import PermissionApprovalRecord, to_utc_naive
from core.permissions.types import (
    ApprovalRequest,
    ApprovalStatus,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from .base import BaseRepository


class ApprovalRepository(BaseRepository):
    """Owns approval persistence and atomic decision/consumption transitions."""

    @staticmethod
    def _to_contract(record: PermissionApprovalRecord) -> ApprovalRequest:
        def aware(value):
            if value is None:
                return None
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

        return ApprovalRequest(
            approval_id=record.approval_id,
            request_id=record.request_id,
            action_hash=record.action_hash,
            subject=PermissionSubject(SubjectType(record.subject_type), record.subject_id),
            resource=PermissionResource(ResourceType(record.resource_type), record.resource_id),
            operation=PermissionOperation(record.operation),
            scope=PermissionScope(ScopeType(record.scope_type), record.scope_id, record.owner_id),
            requested_by=record.requested_by,
            created_at=aware(record.created_at),
            expires_at=aware(record.expires_at),
            status=ApprovalStatus(record.status),
            decided_by=record.decided_by,
            decided_at=aware(record.decided_at),
            consumed_at=aware(record.consumed_at),
        )

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        record = PermissionApprovalRecord(
            approval_id=approval.approval_id,
            request_id=approval.request_id,
            action_hash=approval.action_hash,
            subject_type=approval.subject.subject_type.value,
            subject_id=approval.subject.subject_id,
            resource_type=approval.resource.resource_type.value,
            resource_id=approval.resource.resource_id,
            operation=approval.operation.value,
            scope_type=approval.scope.scope_type.value,
            scope_id=approval.scope.scope_id,
            owner_id=approval.scope.owner_id,
            requested_by=approval.requested_by,
            created_at=to_utc_naive(approval.created_at),
            expires_at=to_utc_naive(approval.expires_at),
            status=approval.status.value,
            decided_by=approval.decided_by,
            decided_at=to_utc_naive(approval.decided_at) if approval.decided_at else None,
            consumed_at=to_utc_naive(approval.consumed_at) if approval.consumed_at else None,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        record = self.db.query(PermissionApprovalRecord).filter(
            PermissionApprovalRecord.approval_id == approval_id
        ).first()
        return self._to_contract(record) if record else None

    def decide(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decided_by: str,
        decided_at: datetime,
    ) -> ApprovalRequest | None:
        if status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("Unsupported approval decision.")
        now = to_utc_naive(decided_at)
        expiry_filter = PermissionApprovalRecord.expires_at > now
        result = self.db.execute(
            update(PermissionApprovalRecord)
            .where(
                PermissionApprovalRecord.approval_id == approval_id,
                PermissionApprovalRecord.status == ApprovalStatus.PENDING.value,
                expiry_filter,
            )
            .values(
                status=status.value,
                decided_by=decided_by,
                decided_at=now,
            )
        )
        if result.rowcount:
            self.db.commit()
        else:
            self.db.rollback()
        return self.get(approval_id)

    def consume(
        self,
        approval_id: str,
        *,
        expected: ApprovalRequest,
        action_hash: str,
        consumed_at: datetime,
    ) -> ApprovalRequest | None:
        now = to_utc_naive(consumed_at)
        result = self.db.execute(
            update(PermissionApprovalRecord)
            .where(
                PermissionApprovalRecord.approval_id == approval_id,
                PermissionApprovalRecord.request_id == expected.request_id,
                PermissionApprovalRecord.action_hash == action_hash,
                PermissionApprovalRecord.subject_type == expected.subject.subject_type.value,
                PermissionApprovalRecord.subject_id == expected.subject.subject_id,
                PermissionApprovalRecord.resource_type == expected.resource.resource_type.value,
                PermissionApprovalRecord.resource_id == expected.resource.resource_id,
                PermissionApprovalRecord.operation == expected.operation.value,
                PermissionApprovalRecord.scope_type == expected.scope.scope_type.value,
                PermissionApprovalRecord.scope_id == expected.scope.scope_id,
                PermissionApprovalRecord.owner_id == expected.scope.owner_id,
                PermissionApprovalRecord.status == ApprovalStatus.APPROVED.value,
                PermissionApprovalRecord.expires_at > now,
                PermissionApprovalRecord.consumed_at.is_(None),
            )
            .values(status=ApprovalStatus.CONSUMED.value, consumed_at=now)
        )
        if result.rowcount:
            self.db.commit()
            return self.get(approval_id)
        self.db.rollback()
        return None


    def expire(self, approval_id: str, *, expired_at: datetime) -> ApprovalRequest | None:
        """Expire a pending or approved request after its deadline."""
        now = to_utc_naive(expired_at)
        result = self.db.execute(
            update(PermissionApprovalRecord)
            .where(
                PermissionApprovalRecord.approval_id == approval_id,
                PermissionApprovalRecord.status.in_(
                    (ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value)
                ),
                PermissionApprovalRecord.expires_at <= now,
            )
            .values(status=ApprovalStatus.EXPIRED.value)
        )
        if result.rowcount:
            self.db.commit()
        else:
            self.db.rollback()
        return self.get(approval_id)
