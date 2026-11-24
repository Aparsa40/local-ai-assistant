from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.permissions.approvals import (
    ApprovalDeniedError,
    ApprovalService,
    ApprovalTransitionError,
)
from core.permissions.types import (
    AccessRequest,
    ApprovalStatus,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.repositories.approval_repository import ApprovalRepository


class AllowUserApproval:
    def authorize_approval(self, approver, approval, action: str) -> bool:
        return approver.subject_type is SubjectType.USER and approver.subject_id == "owner-1"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _request() -> AccessRequest:
    return AccessRequest(
        subject=PermissionSubject(SubjectType.SERVICE, "runtime-api"),
        resource=PermissionResource(ResourceType.TOOL, "runtime.unload"),
        operation=PermissionOperation.EXECUTE,
        scope=PermissionScope(ScopeType.LOCAL, "machine", "owner-1"),
        request_id="approval-request-1",
    )


def _service(db_session, *, now=None, policy=None):
    return ApprovalService(
        ApprovalRepository(db_session),
        decision_policy=policy,
        clock=lambda: now or datetime.now(timezone.utc),
    )


def test_approval_is_default_deny_for_decision(db_session) -> None:
    service = _service(db_session)
    approval = service.request(_request(), {"model_id": "qwen:0.5b"}, requested_by="runtime-api")

    with pytest.raises(ApprovalDeniedError):
        service.approve(approval.approval_id, approver=PermissionSubject(SubjectType.USER, "owner-1"))


def test_approval_is_bound_to_exact_request_and_payload_and_consumed_once(db_session) -> None:
    service = _service(db_session, policy=AllowUserApproval())
    request = _request()
    payload = {"runtime_id": "ollama", "model_id": "qwen:0.5b", "keep_alive": "5m"}
    approval = service.request(request, payload, requested_by="runtime-api")
    approved = service.approve(approval.approval_id, approver=PermissionSubject(SubjectType.USER, "owner-1"))

    assert approved.status is ApprovalStatus.APPROVED
    assert service.consume(approval.approval_id, request, {"model_id": "qwen:0.5b", "runtime_id": "ollama", "keep_alive": "5m"}) is not None
    assert service.consume(approval.approval_id, request, payload) is None


def test_approval_rejects_changed_payload_or_request_scope(db_session) -> None:
    service = _service(db_session, policy=AllowUserApproval())
    request = _request()
    payload = {"target": "conversation-1", "operation": "delete"}
    approval = service.request(request, payload, requested_by="runtime-api")
    service.approve(approval.approval_id, approver=PermissionSubject(SubjectType.USER, "owner-1"))

    assert service.consume(approval.approval_id, request, {"target": "conversation-2", "operation": "delete"}) is None
    other_request = AccessRequest(
        subject=request.subject,
        resource=request.resource,
        operation=request.operation,
        scope=PermissionScope(ScopeType.LOCAL, "other-machine", "owner-1"),
        request_id=request.request_id,
    )
    assert service.consume(approval.approval_id, other_request, payload) is None


def test_expired_pending_approval_cannot_be_approved(db_session) -> None:
    now = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)
    service = _service(db_session, now=now, policy=AllowUserApproval())
    approval = service.request(_request(), {"action": "delete"}, requested_by="runtime-api", ttl_seconds=5)

    expired_service = _service(
        db_session,
        now=now + timedelta(seconds=5),
        policy=AllowUserApproval(),
    )
    with pytest.raises(ApprovalTransitionError, match="expired"):
        expired_service.approve(approval.approval_id, approver=PermissionSubject(SubjectType.USER, "owner-1"))

    assert ApprovalRepository(db_session).get(approval.approval_id).status is ApprovalStatus.EXPIRED


def test_approval_cannot_be_decided_twice(db_session) -> None:
    service = _service(db_session, policy=AllowUserApproval())
    approval = service.request(_request(), {"action": "publish"}, requested_by="librarian")
    approver = PermissionSubject(SubjectType.USER, "owner-1")
    service.reject(approval.approval_id, approver=approver)

    with pytest.raises(ApprovalTransitionError):
        service.approve(approval.approval_id, approver=approver)


def test_approval_rejects_invalid_ttl_and_non_json_payload(db_session) -> None:
    service = _service(db_session)

    with pytest.raises(ValueError):
        service.request(_request(), {"action": "run"}, requested_by="runtime-api", ttl_seconds=0)

    with pytest.raises(ValueError):
        service.request(_request(), {"value": object()}, requested_by="runtime-api")
