from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.permissions.manager import PermissionManager, PermissionManagementDeniedError
from core.permissions.types import (
    AccessRequest,
    PermissionGrant,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.repositories.permission_repository import PermissionRepository


class AllowOwnerGrantPolicy:
    def authorize_grant_change(self, issuer, grant, action: str) -> bool:
        return issuer.subject_type is SubjectType.USER and issuer.subject_id == grant.issued_by


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _request(**overrides) -> AccessRequest:
    values = {
        "subject": PermissionSubject(SubjectType.SERVICE, "conversation-api"),
        "resource": PermissionResource(ResourceType.CONVERSATION, "conversation-7"),
        "operation": PermissionOperation.READ,
        "scope": PermissionScope(ScopeType.CONVERSATION, "conversation-7", "owner-1"),
        "request_id": "request-7",
    }
    values.update(overrides)
    return AccessRequest(**values)


def _grant(request: AccessRequest, *, expires_at=None, revoked_at=None) -> PermissionGrant:
    return PermissionGrant(
        grant_id=str(uuid4()),
        subject=request.subject,
        resource=request.resource,
        operation=request.operation,
        scope=request.scope,
        issued_by="owner-1",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def test_permission_manager_defaults_to_deny_without_store() -> None:
    decision = PermissionManager().authorize(_request())

    assert decision.effect.value == "deny"
    assert decision.reason_code == "policy_store_unavailable"


def test_permission_manager_allows_only_exact_active_grant(db_session) -> None:
    repository = PermissionRepository(db_session)
    request = _request()
    grant = _grant(request)
    repository.create(grant)

    decision = PermissionManager(repository).authorize(request)

    assert decision.effect.value == "allow"
    assert decision.grant_id == grant.grant_id


@pytest.mark.parametrize(
    "changed",
    [
        {"resource": PermissionResource(ResourceType.CONVERSATION, "conversation-other")},
        {"operation": PermissionOperation.DELETE},
        {"scope": PermissionScope(ScopeType.CONVERSATION, "conversation-7", "owner-other")},
        {"subject": PermissionSubject(SubjectType.SERVICE, "different-service")},
    ],
)
def test_permission_manager_denies_non_matching_scope_or_subject(db_session, changed) -> None:
    repository = PermissionRepository(db_session)
    request = _request()
    repository.create(_grant(request))

    assert PermissionManager(repository).authorize(_request(**changed)).effect.value == "deny"


def test_expired_and_revoked_grants_do_not_authorize(db_session) -> None:
    repository = PermissionRepository(db_session)
    request = _request()
    now = datetime.now(timezone.utc)
    expired = _grant(request, expires_at=now - timedelta(seconds=1))
    revoked = _grant(request, revoked_at=now - timedelta(seconds=1))
    repository.create(expired)
    repository.create(revoked)

    decision = PermissionManager(repository).authorize(request)

    assert decision.effect.value == "deny"
    assert decision.reason_code == "grant_inactive"


def test_grant_issuance_is_default_deny(db_session) -> None:
    request = _request()
    grant = _grant(request)
    issuer = PermissionSubject(SubjectType.USER, "owner-1")

    with pytest.raises(PermissionManagementDeniedError):
        PermissionManager(PermissionRepository(db_session)).issue_grant(grant, issuer=issuer)


def test_agent_cannot_issue_grant_even_with_permissive_admin_policy(db_session) -> None:
    request = _request()
    grant = _grant(request)
    issuer = PermissionSubject(SubjectType.AGENT_RUN, "agent-run-1")
    manager = PermissionManager(
        PermissionRepository(db_session),
        grant_policy=AllowOwnerGrantPolicy(),
    )

    with pytest.raises(PermissionManagementDeniedError):
        manager.issue_grant(grant, issuer=issuer)


def test_authorized_owner_can_issue_and_revoke_grant(db_session) -> None:
    request = _request()
    grant = _grant(request)
    issuer = PermissionSubject(SubjectType.USER, "owner-1")
    manager = PermissionManager(
        PermissionRepository(db_session),
        grant_policy=AllowOwnerGrantPolicy(),
    )

    stored = manager.issue_grant(grant, issuer=issuer)
    assert manager.authorize(request).effect.value == "allow"

    revoked = manager.revoke_grant(stored.grant_id, issuer=issuer)

    assert revoked is not None
    assert revoked.revoked_at is not None
    assert manager.authorize(request).effect.value == "deny"


def test_repository_round_trips_grant_with_timezone_information(db_session) -> None:
    repository = PermissionRepository(db_session)
    request = _request()
    grant = _grant(request)

    stored = repository.create(grant)
    loaded = repository.get(grant.grant_id)

    assert loaded == stored
    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
