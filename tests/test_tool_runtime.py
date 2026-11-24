import asyncio
from datetime import datetime, timedelta, timezone
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.permissions.approvals import ApprovalService
from core.permissions.audit import AuditPersistenceError, AuditService
from core.permissions.manager import PermissionManager
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
from core.tools.registry import ToolRegistry
from core.tools.runtime import ToolRuntime
from core.tools.schemas import ToolCallRequest, ToolDefinition, ToolRiskClass


class AllowOwnerGrantPolicy:
    def authorize_grant_change(self, issuer, grant, action: str) -> bool:
        return issuer.subject_type is SubjectType.USER and issuer.subject_id == grant.issued_by


class AllowOwnerApprovalPolicy:
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


def _definition(handler_risk=ToolRiskClass.READ_ONLY, *, requires_approval=False, timeout=1, output_schema=None):
    operation = {
        ToolRiskClass.READ_ONLY: PermissionOperation.READ,
        ToolRiskClass.MUTATING: PermissionOperation.UPDATE,
        ToolRiskClass.DESTRUCTIVE: PermissionOperation.DELETE,
        ToolRiskClass.EXTERNAL_SIDE_EFFECT: PermissionOperation.TRANSMIT,
    }[handler_risk]
    return ToolDefinition(
        tool_id="resource.action",
        version="1.0.0",
        description="Bounded test tool.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string", "maxLength": 100}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema=output_schema,
        resource_type=ResourceType.CONVERSATION,
        operation=operation,
        risk_class=handler_risk,
        timeout_seconds=timeout,
        max_input_bytes=1024,
        max_output_bytes=1024,
        requires_approval=requires_approval,
    )


def _access_request(definition, request_id="tool-run-1"):
    return AccessRequest(
        subject=PermissionSubject(SubjectType.SERVICE, "tool-gateway"),
        resource=PermissionResource(ResourceType.CONVERSATION, "conversation-1"),
        operation=definition.operation,
        scope=PermissionScope(ScopeType.CONVERSATION, "conversation-1", "owner-1"),
        request_id=request_id,
    )


def _runtime(db_session, definition, handler, *, requires_approval=False, audit=None):
    repository = PermissionRepository(db_session)
    manager = PermissionManager(repository, grant_policy=AllowOwnerGrantPolicy())
    access = _access_request(definition)
    grant = PermissionGrant(
        grant_id=str(uuid4()),
        subject=access.subject,
        resource=access.resource,
        operation=access.operation,
        scope=access.scope,
        issued_by="owner-1",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        requires_approval=requires_approval,
    )
    manager.issue_grant(grant, issuer=PermissionSubject(SubjectType.USER, "owner-1"))

    registry = ToolRegistry()
    registry.register(definition, handler)
    audit_service = audit or AuditService(AuditRepository(db_session))
    approvals = ApprovalService(
        ApprovalRepository(db_session),
        decision_policy=AllowOwnerApprovalPolicy(),
    )
    runtime = ToolRuntime(registry, manager, audit_service, approval_service=approvals)
    request = ToolCallRequest(
        definition.tool_id,
        definition.version,
        access,
        {"value": "hello"},
    )
    return runtime, request, approvals, audit_service


async def _echo(data):
    return {"result": data["value"]}


def test_runtime_executes_only_after_exact_permission_and_audits_result(db_session) -> None:
    definition = _definition(output_schema={
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
        "additionalProperties": False,
    })
    runtime, request, _approvals, audit = _runtime(db_session, definition, _echo)

    result = asyncio.run(runtime.execute(request))

    assert result.ok is True
    assert result.output == {"result": "hello"}
    assert [item["event_type"] for item in audit.repository.list_for_request(request.access_request.request_id)] == [
        "tool_request",
        "permission_decision",
        "tool_execution",
    ]


def test_runtime_denies_without_a_matching_grant_and_never_calls_handler(db_session) -> None:
    definition = _definition()
    registry = ToolRegistry()
    called = []
    async def handler(data):
        called.append(True)
        return {"result": "should-not-run"}
    registry.register(definition, handler)
    audit = AuditService(AuditRepository(db_session))
    runtime = ToolRuntime(registry, PermissionManager(), audit)
    request = ToolCallRequest(
        definition.tool_id,
        definition.version,
        _access_request(definition),
        {"value": "hello"},
    )

    result = asyncio.run(runtime.execute(request))

    assert result.error_category == "permission_denied"
    assert called == []


def test_runtime_requires_and_consumes_one_time_approval(db_session) -> None:
    definition = _definition()
    runtime, request, approvals, _audit = _runtime(
        db_session, definition, _echo, requires_approval=True
    )
    pending = runtime.request_approval(request, requested_by="tool-gateway")
    approvals.approve(pending.approval_id, approver=PermissionSubject(SubjectType.USER, "owner-1"))
    approved_request = ToolCallRequest(
        request.tool_id,
        request.version,
        request.access_request,
        request.input_data,
        approval_id=pending.approval_id,
    )

    first = asyncio.run(runtime.execute(approved_request))
    second = asyncio.run(runtime.execute(approved_request))

    assert first.ok is True
    assert second.error_category == "approval_invalid"


def test_runtime_rejects_missing_approval_for_high_risk_tool(db_session) -> None:
    definition = _definition(ToolRiskClass.DESTRUCTIVE, requires_approval=True)
    runtime, request, _approvals, _audit = _runtime(db_session, definition, _echo)

    result = asyncio.run(runtime.execute(request))

    assert result.error_category == "approval_required"


def test_runtime_enforces_handler_timeout_and_reports_possible_side_effect(db_session) -> None:
    definition = _definition(ToolRiskClass.MUTATING, timeout=1)
    async def slow_handler(data):
        await asyncio.sleep(2)
        return {"result": "late"}
    runtime, request, _approvals, _audit = _runtime(db_session, definition, slow_handler)

    result = asyncio.run(runtime.execute(request))

    assert result.error_category == "tool_timeout"
    assert result.side_effect_may_have_occurred is True


def test_runtime_normalizes_handler_exception_without_leaking_message(db_session) -> None:
    definition = _definition()
    async def broken_handler(data):
        raise RuntimeError("api_key=sk-super-secret-value")
    runtime, request, _approvals, audit = _runtime(db_session, definition, broken_handler)

    result = asyncio.run(runtime.execute(request))
    events = audit.repository.list_for_request(request.access_request.request_id)

    assert result.error_category == "tool_execution_failed"
    assert "super-secret" not in (result.error_message or "")
    assert events[-1]["metadata"]["exception_type"] == "RuntimeError"
    assert "api_key" not in str(events[-1]["metadata"])


def test_runtime_fails_closed_when_pre_execution_audit_cannot_be_written(db_session) -> None:
    definition = _definition()
    called = []
    async def handler(data):
        called.append(True)
        return {"result": "unexpected"}
    class BrokenAudit:
        def record(self, **kwargs):
            raise AuditPersistenceError("audit unavailable")
    runtime, request, _approvals, _audit = _runtime(
        db_session, definition, handler, audit=BrokenAudit()
    )

    with pytest.raises(AuditPersistenceError):
        asyncio.run(runtime.execute(request))

    assert called == []


def test_runtime_reports_post_execution_audit_failure_without_claiming_no_side_effect(db_session) -> None:
    definition = _definition(ToolRiskClass.MUTATING)
    events = []
    class FailOnThirdEvent:
        def record(self, **kwargs):
            events.append(kwargs)
            if len(events) == 3:
                raise AuditPersistenceError("audit unavailable")
    runtime, request, _approvals, _audit = _runtime(
        db_session, definition, _echo, audit=FailOnThirdEvent()
    )

    result = asyncio.run(runtime.execute(request))

    assert result.error_category == "audit_persistence_failed"
    assert result.side_effect_may_have_occurred is True
