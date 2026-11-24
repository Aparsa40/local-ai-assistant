"""Reusable fail-closed authorization guard for application services."""
from __future__ import annotations

from core.permissions.audit import AuditService
from core.permissions.manager import PermissionManager
from core.permissions.types import (
    AccessContext,
    DecisionEffect,
    PermissionOperation,
    PermissionResource,
    ResourceType,
)


class AccessDeniedError(PermissionError):
    """The requested domain operation was not authorized."""


def require_access(
    permission_manager: PermissionManager | None,
    access_context: AccessContext | None,
    resource_type: ResourceType,
    resource_id: str,
    operation: PermissionOperation,
    *,
    audit_service: AuditService | None = None,
) -> None:
    """Authorize and audit one domain operation before its repository side effect."""
    if permission_manager is None or access_context is None:
        raise AccessDeniedError("An explicit permission manager and access context are required.")
    request = access_context.build_request(
        PermissionResource(resource_type, resource_id),
        operation,
    )
    decision = permission_manager.authorize(request)
    if audit_service is not None:
        audit_service.record(
            event_type="domain_access_decision",
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
    if decision.effect is not DecisionEffect.ALLOW:
        raise AccessDeniedError(decision.reason_code)
