"""Deterministic default-deny permission evaluation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from core.repositories.permission_repository import PermissionRepository
from .policies import DenyAllGrantAdministrationPolicy, GrantAdministrationPolicy
from .types import (
    AccessRequest,
    DecisionEffect,
    PermissionDecision,
    PermissionGrant,
    PermissionSubject,
    SubjectType,
)


class PermissionGrantStore(Protocol):
    def create(self, grant: PermissionGrant) -> PermissionGrant: ...
    def get(self, grant_id: str) -> PermissionGrant | None: ...
    def list_exact(self, subject, resource, operation, scope) -> tuple[PermissionGrant, ...]: ...
    def revoke(self, grant_id: str, *, revoked_at: datetime) -> PermissionGrant | None: ...


class PermissionManagementDeniedError(PermissionError):
    """A caller is not authorized to issue or revoke permission grants."""


class PermissionManager:
    """Single application-side decision point for exact-scope permission requests.

    Authorization defaults to deny when no grant store is supplied, no exact active
    grant exists, or the grant store fails. Grant administration is a separate
    authority and defaults to deny independently from ordinary access decisions.
    """

    def __init__(
        self,
        repository: PermissionGrantStore | PermissionRepository | None = None,
        *,
        grant_policy: GrantAdministrationPolicy | None = None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.grant_policy = grant_policy or DenyAllGrantAdministrationPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def authorize(self, request: AccessRequest) -> PermissionDecision:
        """Evaluate one immutable request; unexpected storage failures fail closed."""
        if not isinstance(request, AccessRequest):
            raise TypeError("request must be an AccessRequest")

        if self.repository is None:
            return PermissionDecision(
                DecisionEffect.DENY, "policy_store_unavailable", request.request_id
            )

        try:
            grants = self.repository.list_exact(
                request.subject, request.resource, request.operation, request.scope
            )
        except Exception:
            return PermissionDecision(
                DecisionEffect.DENY, "policy_store_error", request.request_id
            )

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            return PermissionDecision(
                DecisionEffect.DENY, "invalid_policy_clock", request.request_id
            )

        active = next((grant for grant in grants if grant.is_active(now)), None)
        if active is not None:
            return PermissionDecision(
                DecisionEffect.ALLOW,
                "matching_active_grant",
                request.request_id,
                grant_id=active.grant_id,
                decided_at=now,
            )

        reason = "grant_inactive" if grants else "no_matching_grant"
        return PermissionDecision(DecisionEffect.DENY, reason, request.request_id, decided_at=now)

    def issue_grant(
        self,
        grant: PermissionGrant,
        *,
        issuer: PermissionSubject,
    ) -> PermissionGrant:
        """Persist a grant only after a separate trusted grant-administration check."""
        if not isinstance(grant, PermissionGrant) or not isinstance(issuer, PermissionSubject):
            raise TypeError("grant and issuer must use permission contract types")
        if issuer.subject_type in {SubjectType.AGENT_TYPE, SubjectType.AGENT_RUN}:
            raise PermissionManagementDeniedError("Agent subjects cannot administer permissions.")
        if issuer.subject_id != grant.issued_by:
            raise PermissionManagementDeniedError("Grant issuer identity does not match.")
        if grant.revoked_at is not None:
            raise ValueError("A newly issued grant cannot already be revoked.")
        if self.repository is None:
            raise PermissionManagementDeniedError("Permission storage is unavailable.")
        if not self.grant_policy.authorize_grant_change(issuer, grant, "issue"):
            raise PermissionManagementDeniedError("Grant issuance is not authorized.")
        try:
            return self.repository.create(grant)
        except Exception as exc:
            raise RuntimeError("Permission grant could not be persisted.") from exc

    def revoke_grant(
        self,
        grant_id: str,
        *,
        issuer: PermissionSubject,
    ) -> PermissionGrant | None:
        """Revoke one grant after trusted administration authorization."""
        if not isinstance(issuer, PermissionSubject):
            raise TypeError("issuer must be a PermissionSubject")
        if issuer.subject_type in {SubjectType.AGENT_TYPE, SubjectType.AGENT_RUN}:
            raise PermissionManagementDeniedError("Agent subjects cannot administer permissions.")
        if self.repository is None:
            raise PermissionManagementDeniedError("Permission storage is unavailable.")
        try:
            grant = self.repository.get(grant_id)
        except Exception as exc:
            raise RuntimeError("Permission grant could not be read.") from exc
        if grant is None:
            return None
        if not self.grant_policy.authorize_grant_change(issuer, grant, "revoke"):
            raise PermissionManagementDeniedError("Grant revocation is not authorized.")
        try:
            return self.repository.revoke(grant_id, revoked_at=self._clock())
        except Exception as exc:
            raise RuntimeError("Permission grant could not be revoked.") from exc
