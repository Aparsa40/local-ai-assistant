"""Narrow local-owner policies for grant and approval administration."""
from __future__ import annotations

from core.permissions.types import (
    ApprovalStatus,
    PermissionGrant,
    PermissionSubject,
    SubjectType,
)


class LocalOwnerGrantAdministrationPolicy:
    """Allow only the fixed local owner to manage grants for their own data.

    This policy is valid only behind the loopback-only API boundary. It is not
    authentication and must not be reused for hosted or multi-user deployments.
    """

    OWNER_ID = "local-user"
    _ALLOWED_RESOURCE_TYPES = {
        "conversation",
        "memory_scope",
        "tool",
        "knowledge_source",
        "file",
    }

    def authorize_grant_change(
        self,
        issuer: PermissionSubject,
        grant: PermissionGrant,
        action: str,
    ) -> bool:
        return (
            isinstance(issuer, PermissionSubject)
            and issuer.subject_type is SubjectType.USER
            and issuer.subject_id == self.OWNER_ID
            and isinstance(grant, PermissionGrant)
            and grant.issued_by == self.OWNER_ID
            and grant.scope.owner_id == self.OWNER_ID
            and grant.resource.resource_type.value in self._ALLOWED_RESOURCE_TYPES
            and action in {"issue", "revoke"}
        )


class LocalOwnerApprovalDecisionPolicy:
    """Allow explicit local-owner approval decisions only for local-owned scopes."""

    OWNER_ID = "local-user"

    def authorize_approval(self, approver, approval, action: str) -> bool:
        return (
            isinstance(approver, PermissionSubject)
            and approver.subject_type is SubjectType.USER
            and approver.subject_id == self.OWNER_ID
            and getattr(getattr(approval, "scope", None), "owner_id", None) == self.OWNER_ID
            and action in {ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value}
        )
