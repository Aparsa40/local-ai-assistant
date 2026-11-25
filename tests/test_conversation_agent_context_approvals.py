from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.migrations import run_migrations
from core.conversation_agent.context_approvals import (
    ContextApprovalRequired,
    ConversationContextApprovalCoordinator,
)
from core.permissions.approvals import ApprovalService
from core.permissions.audit import AuditService
from core.permissions.knowledge_adapter import PermissionManagerKnowledgeAccessPolicy
from core.permissions.local_policy import LocalApplicationPolicy
from core.permissions.memory_adapter import PermissionManagerMemoryAccessPolicy
from core.permissions.manager import PermissionManager
from core.permissions.owner_policies import LocalOwnerApprovalDecisionPolicy
from core.permissions.types import (
    AccessRequest,
    DecisionEffect,
    PermissionDecision,
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


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    return engine, sessionmaker(bind=engine)()


def access_request(*, resource_type=ResourceType.MEMORY_SCOPE, request_id="context-request-1"):
    return AccessRequest(
        subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
        resource=PermissionResource(resource_type, "profile-1"),
        operation=PermissionOperation.READ,
        scope=PermissionScope(ScopeType.USER, "profile-1", "local-user"),
        request_id=request_id,
    )


def test_context_approval_is_request_bound_and_consumed_once():
    engine, db = make_db()
    try:
        approval_service = ApprovalService(
            ApprovalRepository(db),
            AuditService(AuditRepository(db)),
            decision_policy=LocalOwnerApprovalDecisionPolicy(),
        )
        coordinator = ConversationContextApprovalCoordinator(
            approval_service,
            request_id="context-request-1",
            owner_id="local-user",
        )
        request = access_request()
        payload = {
            "domain": "memory",
            "action": "read",
            "scope_type": "user",
            "scope_id": "profile-1",
            "owner_id": "local-user",
        }

        with pytest.raises(ContextApprovalRequired) as raised:
            coordinator.authorize(request, payload, "memory")
        pending = raised.value
        approval = coordinator.request(pending)
        approval_service.approve(
            approval.approval_id,
            approver=PermissionSubject(SubjectType.USER, "local-user"),
        )
        coordinator.accept(pending, approval.approval_id)

        changed_payload = {**payload, "scope_id": "another-scope"}
        with pytest.raises(ContextApprovalRequired):
            coordinator.authorize(request, changed_payload, "memory")

        assert coordinator.authorize(request, payload, "memory") is True
        assert ApprovalRepository(db).get(approval.approval_id).status.value == "consumed"
        with pytest.raises(ContextApprovalRequired):
            coordinator.authorize(request, payload, "memory")
    finally:
        db.close()
        engine.dispose()


class RequireApprovalManager:
    def authorize(self, request):
        return PermissionDecision(
            DecisionEffect.REQUIRE_APPROVAL,
            "matching_grant_requires_approval",
            request.request_id,
        )


@pytest.mark.parametrize(
    ("policy_type", "resource_type", "domain"),
    [
        (PermissionManagerMemoryAccessPolicy, ResourceType.MEMORY_SCOPE, "memory"),
        (PermissionManagerKnowledgeAccessPolicy, ResourceType.KNOWLEDGE_SOURCE, "knowledge"),
    ],
)
def test_context_adapters_preserve_request_identity_for_approval(
    policy_type, resource_type, domain,
):
    seen = []

    def approval_handler(request, payload, request_domain):
        seen.append((request, payload, request_domain))
        return True

    policy = policy_type(
        RequireApprovalManager(),
        PermissionSubject(SubjectType.SERVICE, "local-api"),
        approval_handler=approval_handler,
        request_id="context-request-1",
    )
    assert policy.authorize("user", "profile-1", "local-user", "read") is True
    request, payload, request_domain = seen[0]
    assert request.request_id == "context-request-1"
    assert request.resource.resource_type is resource_type
    assert payload["action"] == "read"
    assert request_domain == domain
