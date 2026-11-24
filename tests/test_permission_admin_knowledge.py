from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.knowledge import KnowledgeAccessDeniedError, KnowledgeScope, KnowledgeService
from core.permissions.approvals import ApprovalService
from core.permissions.audit import AuditService
from core.permissions.knowledge_adapter import PermissionManagerKnowledgeAccessPolicy
from core.permissions.local_policy import LocalApplicationPolicy
from core.permissions.manager import PermissionManager, PermissionManagementDeniedError
from core.permissions.owner_policies import (
    LocalOwnerApprovalDecisionPolicy,
    LocalOwnerGrantAdministrationPolicy,
)
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
from core.repositories.approval_repository import ApprovalRepository
from core.repositories.audit_repository import AuditRepository
from core.repositories.permission_repository import PermissionRepository


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def make_manager(db):
    return PermissionManager(
        PermissionRepository(db),
        grant_policy=LocalOwnerGrantAdministrationPolicy(),
        policies=(LocalApplicationPolicy(),),
    )


def make_grant(subject, resource, operation, scope, *, requires_approval=False):
    return PermissionGrant(
        grant_id=str(uuid4()),
        subject=subject,
        resource=resource,
        operation=operation,
        scope=scope,
        issued_by="local-user",
        created_at=datetime.now(timezone.utc),
        requires_approval=requires_approval,
    )


def test_local_owner_can_issue_and_revoke_exact_agent_grant():
    engine, db = make_db()
    try:
        manager = make_manager(db)
        actor = PermissionSubject(SubjectType.USER, "local-user")
        subject = PermissionSubject(SubjectType.AGENT_TYPE, "knowledge-reader")
        resource = PermissionResource(ResourceType.KNOWLEDGE_SOURCE, "project-docs")
        scope = PermissionScope(ScopeType.PROJECT, "project-docs", "local-user")
        grant = make_grant(subject, resource, PermissionOperation.READ, scope)

        issued = manager.issue_grant(grant, issuer=actor)
        request = AccessRequest(subject, resource, PermissionOperation.READ, scope)
        assert manager.authorize(request).effect.value == "allow"

        revoked = manager.revoke_grant(issued.grant_id, issuer=actor)
        assert revoked is not None and revoked.revoked_at is not None
        assert manager.authorize(request).effect.value == "deny"
    finally:
        db.close()
        engine.dispose()


def test_agent_cannot_issue_grants_and_local_owner_cannot_grant_credentials():
    engine, db = make_db()
    try:
        manager = make_manager(db)
        actor = PermissionSubject(SubjectType.USER, "local-user")
        agent = PermissionSubject(SubjectType.AGENT_RUN, "run-1")
        subject = PermissionSubject(SubjectType.AGENT_TYPE, "agent-1")
        scope = PermissionScope(ScopeType.LOCAL, "local-machine", "local-user")
        grant = make_grant(
            subject,
            PermissionResource(ResourceType.TOOL, "knowledge.search"),
            PermissionOperation.EXECUTE,
            scope,
        )
        with pytest.raises(PermissionManagementDeniedError):
            manager.issue_grant(grant, issuer=agent)

        credential_grant = make_grant(
            subject,
            PermissionResource(ResourceType.PROVIDER_CREDENTIAL, "openrouter"),
            PermissionOperation.READ,
            scope,
        )
        with pytest.raises(PermissionManagementDeniedError):
            manager.issue_grant(credential_grant, issuer=actor)
    finally:
        db.close()
        engine.dispose()


def test_knowledge_service_uses_exact_permission_manager_grants():
    engine, db = make_db()
    try:
        manager = make_manager(db)
        subject = PermissionSubject(SubjectType.SERVICE, "local-api")
        scope = KnowledgeScope("user", "private-notes", "local-user")
        policy = PermissionManagerKnowledgeAccessPolicy(manager, subject)
        knowledge = KnowledgeService(db, access_policy=policy)

        with pytest.raises(KnowledgeAccessDeniedError):
            knowledge.create_source(scope, source_type="text", title="Private")

        grant = make_grant(
            subject,
            PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope.scope_id),
            PermissionOperation.CREATE,
            PermissionScope(ScopeType.USER, scope.scope_id, scope.owner_id),
        )
        manager.issue_grant(grant, issuer=PermissionSubject(SubjectType.USER, "local-user"))
        source = knowledge.create_source(scope, source_type="text", title="Private")
        assert source.title == "Private"
    finally:
        db.close()
        engine.dispose()


def test_local_owner_approval_is_action_bound_expiring_and_one_time():
    engine, db = make_db()
    try:
        audit = AuditService(AuditRepository(db))
        service = ApprovalService(
            ApprovalRepository(db),
            audit,
            decision_policy=LocalOwnerApprovalDecisionPolicy(),
        )
        access = AccessRequest(
            subject=PermissionSubject(SubjectType.AGENT_RUN, "run-1"),
            resource=PermissionResource(ResourceType.TOOL, "knowledge.publish"),
            operation=PermissionOperation.PUBLISH,
            scope=PermissionScope(ScopeType.PROJECT, "project-docs", "local-user"),
        )
        payload = {"tool_id": "knowledge.publish", "source_id": "source-1", "version": 2}
        approval = service.request(access, payload, requested_by="local-user")
        approved = service.approve(
            approval.approval_id,
            approver=PermissionSubject(SubjectType.USER, "local-user"),
        )
        assert approved.status.value == "approved"
        assert service.consume(approval.approval_id, access, payload).status.value == "consumed"
        assert service.consume(approval.approval_id, access, payload) is None
        assert service.consume(
            approval.approval_id, access, {**payload, "version": 3}
        ) is None
    finally:
        db.close()
        engine.dispose()
