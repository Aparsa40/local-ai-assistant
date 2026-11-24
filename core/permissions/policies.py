"""Trusted policy hooks for permission issuance and revocation."""
from __future__ import annotations

from typing import Protocol

from .types import PermissionGrant, PermissionSubject


class GrantAdministrationPolicy(Protocol):
    """Application-owned authority for changing the grant registry."""

    def authorize_grant_change(
        self,
        issuer: PermissionSubject,
        grant: PermissionGrant,
        action: str,
    ) -> bool: ...


class DenyAllGrantAdministrationPolicy:
    """Safe default: ordinary callers cannot issue or revoke permission grants."""

    def authorize_grant_change(
        self,
        issuer: PermissionSubject,
        grant: PermissionGrant,
        action: str,
    ) -> bool:
        return False


class ApprovalDecisionPolicy(Protocol):
    """Trusted application authority for approving or rejecting a pending action."""

    def authorize_approval(self, approver: PermissionSubject, approval: object, action: str) -> bool: ...


class DenyAllApprovalDecisionPolicy:
    """Safe default: approval decisions require an explicitly injected authority."""

    def authorize_approval(self, approver: PermissionSubject, approval: object, action: str) -> bool:
        return False

