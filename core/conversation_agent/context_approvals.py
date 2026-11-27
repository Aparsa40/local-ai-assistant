"""Request-bound human approval for scoped conversation context reads."""
from __future__ import annotations

import hashlib
import json

from core.permissions.approvals import ApprovalService
from core.permissions.types import AccessRequest, ApprovalRequest, ApprovalStatus


class ContextApprovalRequired(Exception):
    """A memory/knowledge read is allowed only after a one-time user decision."""

    def __init__(self, access_request: AccessRequest, action_payload: dict, domain: str) -> None:
        super().__init__("Context access requires an explicit user approval.")
        self.access_request = access_request
        self.action_payload = dict(action_payload)
        self.domain = domain


class ConversationContextApprovalCoordinator:
    """Bind one context approval to the exact request, resource, operation and scope."""

    def __init__(
        self,
        approval_service: ApprovalService,
        *,
        request_id: str,
        owner_id: str,
        ttl_seconds: int = 300,
    ) -> None:
        if not isinstance(approval_service, ApprovalService):
            raise TypeError("approval_service must be an ApprovalService")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id is required")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id is required")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        self.approval_service = approval_service
        self.request_id = request_id
        self.owner_id = owner_id
        self.ttl_seconds = ttl_seconds
        self._approved: dict[str, str] = {}

    @staticmethod
    def _key(access_request: AccessRequest, action_payload: dict, domain: str) -> str:
        material = {
            "domain": domain,
            "request_id": access_request.request_id,
            "subject": [access_request.subject.subject_type.value, access_request.subject.subject_id],
            "resource": [access_request.resource.resource_type.value, access_request.resource.resource_id],
            "operation": access_request.operation.value,
            "scope": [
                access_request.scope.scope_type.value,
                access_request.scope.scope_id,
                access_request.scope.owner_id,
            ],
            "action_payload": action_payload,
        }
        encoded = json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def authorize(self, access_request: AccessRequest, action_payload: dict, domain: str) -> bool:
        """Raise on first REQUIRE_APPROVAL; consume the approved token exactly once."""
        if (
            access_request.request_id != self.request_id
            or access_request.scope.owner_id != self.owner_id
            or domain not in {"memory", "knowledge"}
        ):
            return False
        key = self._key(access_request, action_payload, domain)
        approval_id = self._approved.get(key)
        if approval_id is None:
            raise ContextApprovalRequired(access_request, dict(action_payload), domain)
        consumed = self.approval_service.consume(approval_id, access_request, action_payload)
        self._approved.pop(key, None)
        return consumed is not None

    def request(self, pending: ContextApprovalRequired) -> ApprovalRequest:
        if pending.access_request.request_id != self.request_id:
            raise ValueError("Context approval request identity does not match.")
        if pending.access_request.scope.owner_id != self.owner_id:
            raise ValueError("Context approval owner does not match.")
        return self.approval_service.request(
            pending.access_request,
            pending.action_payload,
            requested_by=self.owner_id,
            ttl_seconds=self.ttl_seconds,
        )

    def status(self, approval_id: str) -> ApprovalRequest | None:
        session = getattr(self.approval_service.repository, "db", None)
        if session is not None:
            if hasattr(session, "rollback"):
                session.rollback()
            if hasattr(session, "expire_all"):
                session.expire_all()
        return self.approval_service.repository.get(approval_id)

    def accept(self, pending: ContextApprovalRequired, approval_id: str) -> None:
        approval = self.status(approval_id)
        if approval is None or approval.status is not ApprovalStatus.APPROVED:
            raise ValueError("Only an approved context request can be resumed.")
        if approval.request_id != pending.access_request.request_id:
            raise ValueError("Approved context request identity does not match.")
        if (
            approval.subject != pending.access_request.subject
            or approval.resource != pending.access_request.resource
            or approval.operation is not pending.access_request.operation
            or approval.scope != pending.access_request.scope
        ):
            raise ValueError("Approved context request does not match the pending action.")
        self._approved[self._key(
            pending.access_request, pending.action_payload, pending.domain
        )] = approval_id
