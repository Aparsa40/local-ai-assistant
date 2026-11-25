"""Adapter that routes MemoryService policy checks through PermissionManager."""
from __future__ import annotations

from typing import Callable
from uuid import uuid4

from core.permissions.audit import AuditService
from core.permissions.manager import PermissionManager
from core.permissions.types import (
    AccessContext,
    AccessRequest,
    DecisionEffect,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
)


class PermissionManagerMemoryAccessPolicy:
    """Preserves MemoryService's policy protocol while using central authorization."""

    _OPERATIONS = {
        "create": PermissionOperation.CREATE,
        "read": PermissionOperation.READ,
        "activate": PermissionOperation.UPDATE,
        "update": PermissionOperation.UPDATE,
        "supersede": PermissionOperation.UPDATE,
        "expire": PermissionOperation.UPDATE,
        "delete": PermissionOperation.DELETE,
    }

    def __init__(
        self,
        permission_manager: PermissionManager,
        subject: PermissionSubject,
        *,
        audit_service: AuditService | None = None,
        approval_handler: Callable[[AccessRequest, dict, str], bool] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.permission_manager = permission_manager
        self.subject = subject
        self.audit_service = audit_service
        self.approval_handler = approval_handler
        self.request_id = request_id

    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        operation = self._OPERATIONS.get(action)
        if operation is None:
            return False
        try:
            scope = PermissionScope(ScopeType(scope_type), scope_id, owner_id)
            context = AccessContext(self.subject, scope, request_id=self.request_id or str(uuid4()))
            request = context.build_request(
                PermissionResource(ResourceType.MEMORY_SCOPE, scope_id),
                operation,
            )
        except (TypeError, ValueError):
            return False

        decision = self.permission_manager.authorize(request)
        if self.audit_service is not None:
            self.audit_service.record(
                event_type="memory_access_decision",
                request_id=request.request_id,
                outcome=decision.effect.value,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                metadata={
                    "decision": decision.effect.value,
                    "reason_code": decision.reason_code,
                },
            )
        if decision.effect is DecisionEffect.ALLOW:
            return True
        if decision.effect is DecisionEffect.REQUIRE_APPROVAL and self.approval_handler is not None:
            action_payload = {
                "domain": "memory",
                "action": action,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "owner_id": owner_id,
            }
            return bool(self.approval_handler(request, action_payload, "memory"))
        return False
