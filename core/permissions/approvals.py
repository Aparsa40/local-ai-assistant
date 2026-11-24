"""Action-bound, expiring, one-time approval workflow."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

from core.repositories.approval_repository import ApprovalRepository
from .policies import ApprovalDecisionPolicy, DenyAllApprovalDecisionPolicy
from .types import (
    AccessRequest,
    ApprovalRequest,
    ApprovalStatus,
    PermissionSubject,
    SubjectType,
)


class ApprovalServiceError(Exception):
    """Base class for expected approval workflow errors."""


class ApprovalNotFoundError(ApprovalServiceError):
    """The requested approval does not exist."""


class ApprovalDeniedError(ApprovalServiceError):
    """The caller is not authorized to decide an approval."""


class ApprovalTransitionError(ApprovalServiceError):
    """The approval is expired or no longer pending."""


class ApprovalService:
    """Creates action-hash-bound approvals and consumes each approval at most once."""

    MAX_TTL_SECONDS = 3600
    MAX_ACTION_BYTES = 64 * 1024

    def __init__(
        self,
        repository: ApprovalRepository,
        *,
        decision_policy: ApprovalDecisionPolicy | None = None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.decision_policy = decision_policy or DenyAllApprovalDecisionPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def _action_hash(cls, payload: dict) -> str:
        if not isinstance(payload, dict):
            raise ValueError("Action payload must be a JSON object.")
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Action payload must contain JSON-compatible values.") from exc
        if len(encoded) > cls.MAX_ACTION_BYTES:
            raise ValueError("Action payload exceeds the configured size limit.")
        return hashlib.sha256(encoded).hexdigest()

    def request(
        self,
        access_request: AccessRequest,
        action_payload: dict,
        *,
        requested_by: str,
        ttl_seconds: int = 300,
    ) -> ApprovalRequest:
        if not isinstance(access_request, AccessRequest):
            raise TypeError("access_request must be an AccessRequest")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= self.MAX_TTL_SECONDS:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        if not isinstance(requested_by, str) or not requested_by.strip() or len(requested_by.strip()) > 160:
            raise ValueError("requested_by must contain 1..160 characters")

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("Approval clock must return a timezone-aware datetime.")
        approval = ApprovalRequest(
            approval_id=str(uuid4()),
            request_id=access_request.request_id,
            action_hash=self._action_hash(action_payload),
            subject=access_request.subject,
            resource=access_request.resource,
            operation=access_request.operation,
            scope=access_request.scope,
            requested_by=requested_by.strip(),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        return self.repository.create(approval)

    def _decide(
        self,
        approval_id: str,
        approver: PermissionSubject,
        status: ApprovalStatus,
    ) -> ApprovalRequest:
        if not isinstance(approver, PermissionSubject):
            raise TypeError("approver must be a PermissionSubject")
        if approver.subject_type is not SubjectType.USER:
            raise ApprovalDeniedError("Only an explicitly authorized user can decide an approval.")
        approval = self.repository.get(approval_id)
        if approval is None:
            raise ApprovalNotFoundError("Approval request was not found.")
        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalTransitionError("Approval request is no longer pending.")
        if not self.decision_policy.authorize_approval(approver, approval, status.value):
            raise ApprovalDeniedError("Approval decision is not authorized.")

        now = self._clock()
        if now >= approval.expires_at:
            self.repository.decide(
                approval_id,
                status=ApprovalStatus.EXPIRED,
                decided_by=approver.subject_id,
                decided_at=now,
            )
            raise ApprovalTransitionError("Approval request has expired.")

        updated = self.repository.decide(
            approval_id,
            status=status,
            decided_by=approver.subject_id,
            decided_at=now,
        )
        if updated is None:
            raise ApprovalNotFoundError("Approval request was not found.")
        if updated.status is ApprovalStatus.EXPIRED:
            raise ApprovalTransitionError("Approval request has expired.")
        if updated.status is not status:
            raise ApprovalTransitionError("Approval request was already decided.")
        return updated

    def approve(self, approval_id: str, *, approver: PermissionSubject) -> ApprovalRequest:
        return self._decide(approval_id, approver, ApprovalStatus.APPROVED)

    def reject(self, approval_id: str, *, approver: PermissionSubject) -> ApprovalRequest:
        return self._decide(approval_id, approver, ApprovalStatus.REJECTED)

    def consume(
        self,
        approval_id: str,
        access_request: AccessRequest,
        action_payload: dict,
    ) -> ApprovalRequest | None:
        """Atomically consume an approved token for the same exact action only."""
        if not isinstance(access_request, AccessRequest):
            raise TypeError("access_request must be an AccessRequest")
        approval = self.repository.get(approval_id)
        if approval is None or approval.status is not ApprovalStatus.APPROVED:
            return None

        same_request = (
            approval.request_id == access_request.request_id
            and approval.subject == access_request.subject
            and approval.resource == access_request.resource
            and approval.operation is access_request.operation
            and approval.scope == access_request.scope
        )
        if not same_request:
            return None

        action_hash = self._action_hash(action_payload)
        if not hmac.compare_digest(approval.action_hash, action_hash):
            return None

        now = self._clock()
        if now >= approval.expires_at:
            self.repository.decide(
                approval_id,
                status=ApprovalStatus.EXPIRED,
                decided_by=approval.decided_by or approval.requested_by,
                decided_at=now,
            )
            return None
        return self.repository.consume(
            approval_id,
            expected=approval,
            action_hash=action_hash,
            consumed_at=now,
        )
