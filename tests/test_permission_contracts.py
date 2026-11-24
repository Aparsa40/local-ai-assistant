from datetime import datetime, timedelta, timezone

import pytest

from core.permissions.types import (
    AccessRequest,
    DataSensitivity,
    DecisionEffect,
    PermissionDecision,
    PermissionGrant,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)


def _access_request() -> AccessRequest:
    return AccessRequest(
        subject=PermissionSubject(SubjectType.SERVICE, "conversation-api"),
        resource=PermissionResource(ResourceType.CONVERSATION, "conversation-42"),
        operation=PermissionOperation.READ,
        scope=PermissionScope(ScopeType.CONVERSATION, "conversation-42", "local-user"),
        request_id="request-42",
        sensitivity=DataSensitivity.PRIVATE,
    )


def test_access_request_is_typed_and_has_explicit_scope() -> None:
    request = _access_request()

    assert request.subject.subject_id == "conversation-api"
    assert request.resource.resource_id == "conversation-42"
    assert request.operation is PermissionOperation.READ
    assert request.scope.owner_id == "local-user"
    assert request.sensitivity is DataSensitivity.PRIVATE
    assert request.requested_at.tzinfo is not None


@pytest.mark.parametrize("identifier", ["", "  ", "*", "**", "all", "any"])
def test_permission_identifiers_reject_empty_and_wildcard_values(identifier: str) -> None:
    with pytest.raises(ValueError):
        PermissionSubject(SubjectType.USER, identifier)


def test_permission_contracts_reject_untyped_enum_values() -> None:
    with pytest.raises(ValueError):
        PermissionSubject("user", "local-user")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        PermissionResource(ResourceType.FILE, "*")


def test_access_request_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AccessRequest(
            subject=_access_request().subject,
            resource=_access_request().resource,
            operation=PermissionOperation.READ,
            scope=_access_request().scope,
            requested_at=datetime(2026, 1, 1),
        )


def test_permission_decision_requires_a_stable_reason_and_request_reference() -> None:
    decision = PermissionDecision(
        effect=DecisionEffect.DENY,
        reason_code="no_matching_grant",
        request_id="request-42",
    )

    assert decision.effect is DecisionEffect.DENY
    assert decision.reason_code == "no_matching_grant"

    with pytest.raises(ValueError):
        PermissionDecision(DecisionEffect.DENY, "*", "request-42")


def test_grant_is_active_only_inside_its_exact_time_window() -> None:
    now = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)
    grant = PermissionGrant(
        grant_id="grant-42",
        subject=_access_request().subject,
        resource=_access_request().resource,
        operation=PermissionOperation.READ,
        scope=_access_request().scope,
        issued_by="local-owner",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert grant.is_active(now)
    assert grant.is_active(now + timedelta(minutes=59))
    assert not grant.is_active(now - timedelta(seconds=1))
    assert not grant.is_active(now + timedelta(hours=1))


def test_revoked_grant_is_not_active_after_revocation() -> None:
    now = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)
    grant = PermissionGrant(
        grant_id="grant-43",
        subject=_access_request().subject,
        resource=_access_request().resource,
        operation=PermissionOperation.READ,
        scope=_access_request().scope,
        issued_by="local-owner",
        created_at=now,
        revoked_at=now + timedelta(minutes=5),
    )

    assert grant.is_active(now + timedelta(minutes=4))
    assert not grant.is_active(now + timedelta(minutes=5))


def test_grant_rejects_expiry_before_creation() -> None:
    now = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="later than created_at"):
        PermissionGrant(
            grant_id="grant-invalid",
            subject=_access_request().subject,
            resource=_access_request().resource,
            operation=PermissionOperation.READ,
            scope=_access_request().scope,
            issued_by="local-owner",
            created_at=now,
            expires_at=now - timedelta(seconds=1),
        )
