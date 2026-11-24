"""KnowledgeService policy adapter backed by central PermissionManager."""
from __future__ import annotations

from uuid import uuid4

from core.permissions.audit import AuditService
from core.permissions.manager import PermissionManager
from core.permissions.types import (
    AccessRequest,
    DecisionEffect,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
)


class PermissionManagerKnowledgeAccessPolicy:
    """Map explicit Knowledge scope actions to exact central permission decisions.

    A scope-level resource ID is used because KnowledgeService's policy protocol
    authorizes at scope granularity. Every decision still binds owner and scope.
    """

    _OPERATIONS = {
        "read": PermissionOperation.READ,
        "write": PermissionOperation.UPDATE,
    }

    def __init__(
        self,
        permission_manager: PermissionManager,
        subject: PermissionSubject,
        *,
        audit_service: AuditService | None = None,
    ) -> None:
        self.permission_manager = permission_manager
        self.subject = subject
        self.audit_service = audit_service

    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        operation = self._OPERATIONS.get(action)
        if operation is None:
            return False
        try:
            scope = PermissionScope(ScopeType(scope_type), scope_id, owner_id)
            request = AccessRequest(
                subject=self.subject,
                resource=PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope_id),
                operation=operation,
                scope=scope,
                request_id=str(uuid4()),
            )
        except (TypeError, ValueError):
            return False
        decision = self.permission_manager.authorize(request)
        if self.audit_service is not None:
            self.audit_service.record(
                event_type="knowledge_access_decision",
                request_id=request.request_id,
                outcome=decision.effect.value,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                metadata={
                    "decision": decision.effect.value,
                    "reason_code": decision.reason_code,
                    "grant_id": decision.grant_id or "",
                },
            )
        return decision.effect is DecisionEffect.ALLOW
