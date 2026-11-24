"""Narrow local-only policy for the current single-user application boundary."""
from __future__ import annotations

from core.permissions.types import (
    AccessRequest,
    DecisionEffect,
    PermissionDecision,
    PermissionOperation,
    ResourceType,
    ScopeType,
    SubjectType,
)


class LocalApplicationPolicy:
    """Authorize only the loopback API's fixed local principal and owner scope.

    This is not authentication and must never be treated as a hosted multi-user
    policy. The API dependency must independently reject non-loopback clients.
    """

    SUBJECT_ID = "local-api"
    OWNER_ID = "local-user"
    LOCAL_SCOPE_ID = "local-machine"

    _OPERATIONS = {
        ResourceType.CONVERSATION: {
            PermissionOperation.READ,
            PermissionOperation.CREATE,
            PermissionOperation.UPDATE,
            PermissionOperation.DELETE,
        },
        ResourceType.PROFILE: {
            PermissionOperation.READ,
            PermissionOperation.UPDATE,
            PermissionOperation.DELETE,
        },
        ResourceType.MEMORY_SCOPE: {
            PermissionOperation.READ,
            PermissionOperation.CREATE,
            PermissionOperation.UPDATE,
            PermissionOperation.DELETE,
        },
        ResourceType.CONFIGURATION: {PermissionOperation.READ, PermissionOperation.UPDATE},
        ResourceType.PROVIDER: {PermissionOperation.READ, PermissionOperation.EXECUTE},
        ResourceType.RUNTIME: {PermissionOperation.READ, PermissionOperation.EXECUTE, PermissionOperation.ADMINISTER},
    }

    def evaluate(self, request: AccessRequest) -> PermissionDecision | None:
        if (
            request.subject.subject_type is not SubjectType.SERVICE
            or request.subject.subject_id != self.SUBJECT_ID
        ):
            return None

        reason = "local_policy_denied"
        allowed_operations = self._OPERATIONS.get(request.resource.resource_type)
        if allowed_operations is None or request.operation not in allowed_operations:
            return PermissionDecision(DecisionEffect.DENY, reason, request.request_id)

        if request.scope.owner_id != self.OWNER_ID:
            return PermissionDecision(DecisionEffect.DENY, "local_owner_mismatch", request.request_id)

        if request.resource.resource_type in {
            ResourceType.CONVERSATION,
            ResourceType.PROFILE,
            ResourceType.CONFIGURATION,
            ResourceType.PROVIDER,
            ResourceType.RUNTIME,
        }:
            if (
                request.scope.scope_type is not ScopeType.LOCAL
                or request.scope.scope_id != self.LOCAL_SCOPE_ID
            ):
                return PermissionDecision(DecisionEffect.DENY, "local_scope_mismatch", request.request_id)
            if (
                request.resource.resource_type is ResourceType.PROFILE
                and request.resource.resource_id != self.OWNER_ID
            ):
                return PermissionDecision(DecisionEffect.DENY, "profile_owner_mismatch", request.request_id)
            if (
                request.resource.resource_type is ResourceType.CONFIGURATION
                and request.resource.resource_id != "application-settings"
            ):
                return PermissionDecision(DecisionEffect.DENY, "configuration_resource_mismatch", request.request_id)
        elif request.resource.resource_type is ResourceType.MEMORY_SCOPE:
            if request.scope.scope_type not in {
                ScopeType.USER,
                ScopeType.CONVERSATION,
                ScopeType.TASK,
                ScopeType.GLOBAL,
            }:
                return PermissionDecision(DecisionEffect.DENY, "memory_scope_type_unsupported", request.request_id)
            if request.resource.resource_id != request.scope.scope_id:
                return PermissionDecision(DecisionEffect.DENY, "memory_scope_resource_mismatch", request.request_id)

        return PermissionDecision(
            DecisionEffect.ALLOW,
            "trusted_local_application_policy",
            request.request_id,
        )
