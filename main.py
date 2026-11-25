# pyright: reportMissingImports=false
import ipaddress
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.config_manager import ConfigManager
from core.database import init_db
from core.knowledge import KnowledgeScope, KnowledgeService, KnowledgeAccessDeniedError, KnowledgeNotFoundError, KnowledgeValidationError
from core.conversations import ConversationNotFoundError, ConversationService
from core.context import ContextManager, ContextRequest
from core.profiles import ProfileService, ProfileServiceError
from core.storage.manager import get_storage_manager
from core.permissions.audit import AuditService
from core.permissions.approvals import ApprovalService, ApprovalDeniedError, ApprovalNotFoundError, ApprovalTransitionError
from core.permissions.knowledge_adapter import PermissionManagerKnowledgeAccessPolicy
from core.permissions.owner_policies import LocalOwnerApprovalDecisionPolicy, LocalOwnerGrantAdministrationPolicy
from core.permissions.guards import AccessDeniedError, require_access
from core.permissions.local_policy import LocalApplicationPolicy
from core.permissions.manager import PermissionManager
from core.permissions.types import (AccessContext, ApprovalStatus, PermissionGrant, PermissionOperation, PermissionResource, PermissionScope, PermissionSubject, ResourceType, ScopeType, SubjectType)
from core.repositories.audit_repository import AuditRepository
from core.repositories.approval_repository import ApprovalRepository
from core.repositories.permission_repository import PermissionRepository
from core.orchestrator import Orchestrator
from core.interface_manager import InterfaceManager, InterfaceManagerError
from core.provider_intelligence import (
    create_offline_intelligence_report,
    refresh_provider_intelligence,
)
from core.runtime.factory import build_runtime_manager
from core.runtime.monitor import RuntimeMonitor
from core.catalog_storage import (
    get_operational_report,
    get_provider_catalog_snapshot,
    record_model_runtime,
    record_quota_snapshot,
    seed_operator_catalogs,
    get_latest_intelligence_report,
)
from core.agents import AgentRuntimeContainer
from core.agents.contracts import AgentConcurrencyError, AgentTransitionError, DataScope, StopReason
from core.agents.controller import AgentControllerError
from core.agents.context import AgentScopeDeniedError
from core.agents.lifecycle import RunNotFoundError, TaskNotFoundError
from core.agents.registry import AgentDefinitionError
from core.repositories.agent_repository import AgentDefinitionRepository
from core.repositories.run_repository import AgentRunEventRepository, AgentRunRepository

app = FastAPI(title="Local Modular AI Assistant")
permission_manager = PermissionManager(policies=(LocalApplicationPolicy(),))
storage_manager = get_storage_manager()
SessionLocal = storage_manager.session_factory  # Temporary compatibility for the catalog route fallback.
interface_manager = InterfaceManager()
init_db()
runtime_manager = build_runtime_manager(ConfigManager.load_config, storage_manager.session_factory)
runtime_monitor = RuntimeMonitor(runtime_manager)
with storage_manager.session() as _catalog_seed_db:
    seed_operator_catalogs(_catalog_seed_db)
agent_container = AgentRuntimeContainer(storage_manager, interface_manager)
with storage_manager.session() as _agent_boot_db:
    agent_container.register_builtin_agents(_agent_boot_db)
agent_container.recover_stale_runs()
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_db():
    with storage_manager.session() as db:
        yield db


def get_local_access_context(request: Request) -> AccessContext:
    """Resolve the fixed local principal only for loopback and same-origin requests."""
    client_host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(client_host)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Local access only.") from exc
    mapped_address = getattr(address, "ipv4_mapped", None)
    if not address.is_loopback and not (mapped_address and mapped_address.is_loopback):
        raise HTTPException(status_code=403, detail="Local access only.")

    # Reject cross-origin browser requests to the loopback API (basic CSRF defense).
    origin = request.headers.get("origin")
    if origin:
        parsed_origin = urlsplit(origin)
        origin_host = parsed_origin.hostname or ""
        try:
            origin_address = ipaddress.ip_address(origin_host)
            origin_is_loopback = origin_address.is_loopback
        except ValueError:
            origin_is_loopback = origin_host.lower() == "localhost"
        if (
            not origin_is_loopback
            or parsed_origin.scheme != request.url.scheme
            or parsed_origin.netloc.lower() != request.headers.get("host", "").lower()
        ):
            raise HTTPException(status_code=403, detail="Cross-origin local API requests are not allowed.")

    return AccessContext(
        subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
        scope=PermissionScope(ScopeType.LOCAL, "local-machine", "local-user"),
        request_id=str(uuid4()),
    )


def build_audit_service(db: Session) -> AuditService:
    return AuditService(AuditRepository(db))


def authorize_local_api_access(
    access: AccessContext,
    resource_type: ResourceType,
    resource_id: str,
    operation: PermissionOperation,
    db: Session | None = None,
) -> None:
    if db is not None:
        require_access(
            permission_manager, access, resource_type, resource_id, operation,
            audit_service=build_audit_service(db),
        )
        return
    with storage_manager.session() as audit_db:
        require_access(
            permission_manager, access, resource_type, resource_id, operation,
            audit_service=build_audit_service(audit_db),
        )


@app.exception_handler(AccessDeniedError)
async def handle_access_denied(request: Request, exc: AccessDeniedError):
    return JSONResponse(status_code=403, content={"detail": "Access denied."})


class ChatRequest(BaseModel):
    session_id: int
    message: str = Field(min_length=1, max_length=12000)


class SessionTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=254)


class RuntimeLoadRequest(BaseModel):
    keep_alive: str | int = "5m"



class PermissionGrantCreateRequest(BaseModel):
    subject_type: SubjectType
    subject_id: str = Field(min_length=1, max_length=160)
    resource_type: ResourceType
    resource_id: str = Field(min_length=1, max_length=255)
    operation: PermissionOperation
    scope_type: ScopeType
    scope_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(default="local-user", min_length=1, max_length=160)
    expires_at: datetime | None = None
    requires_approval: bool = False


class KnowledgeSourceCreateRequest(BaseModel):
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(default="local-user", min_length=1, max_length=160)
    source_type: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=300)
    uri: str | None = Field(default=None, max_length=4000)


class KnowledgeIndexRequest(BaseModel):
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(default="local-user", min_length=1, max_length=160)
    extracted_text: str = Field(min_length=1, max_length=5_000_000)
    extractor: str = Field(default="manual", max_length=120)
    extractor_version: str = Field(default="1", max_length=80)


class AgentTaskCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    agent_version: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    query: str = Field(default="", max_length=2000)
    scope_type: str = Field(default="user", min_length=1, max_length=40)
    scope_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(default="local-user", min_length=1, max_length=160)


def build_admin_permission_manager(db: Session) -> PermissionManager:
    return PermissionManager(
        PermissionRepository(db),
        grant_policy=LocalOwnerGrantAdministrationPolicy(),
        policies=(LocalApplicationPolicy(),),
    )


def build_approval_service(db: Session) -> ApprovalService:
    return ApprovalService(
        ApprovalRepository(db),
        build_audit_service(db),
        decision_policy=LocalOwnerApprovalDecisionPolicy(),
    )


def build_knowledge_service(db: Session, access: AccessContext) -> KnowledgeService:
    manager = PermissionManager(
        PermissionRepository(db),
        policies=(LocalApplicationPolicy(),),
    )
    policy = PermissionManagerKnowledgeAccessPolicy(
        manager,
        access.subject,
        audit_service=build_audit_service(db),
    )
    return KnowledgeService(db, access_policy=policy)


def serialize_grant(grant: PermissionGrant) -> dict:
    return {
        "grant_id": grant.grant_id,
        "subject": {"type": grant.subject.subject_type.value, "id": grant.subject.subject_id},
        "resource": {"type": grant.resource.resource_type.value, "id": grant.resource.resource_id},
        "operation": grant.operation.value,
        "scope": {"type": grant.scope.scope_type.value, "id": grant.scope.scope_id, "owner_id": grant.scope.owner_id},
        "issued_by": grant.issued_by,
        "created_at": grant.created_at.isoformat(),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "requires_approval": grant.requires_approval,
        "active": grant.is_active(datetime.now(timezone.utc)),
    }


def serialize_approval(approval) -> dict:
    return {
        "approval_id": approval.approval_id,
        "request_id": approval.request_id,
        "action_hash": approval.action_hash,
        "subject": {"type": approval.subject.subject_type.value, "id": approval.subject.subject_id},
        "resource": {"type": approval.resource.resource_type.value, "id": approval.resource.resource_id},
        "operation": approval.operation.value,
        "scope": {"type": approval.scope.scope_type.value, "id": approval.scope.scope_id, "owner_id": approval.scope.owner_id},
        "requested_by": approval.requested_by,
        "created_at": approval.created_at.isoformat(),
        "expires_at": approval.expires_at.isoformat(),
        "status": approval.status.value,
        "decided_by": approval.decided_by,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "consumed_at": approval.consumed_at.isoformat() if approval.consumed_at else None,
    }


def create_api_approval(
    db: Session,
    access: AccessContext,
    resource_type: ResourceType,
    resource_id: str,
    operation: PermissionOperation,
    payload: dict,
):
    request = access.build_request(
        PermissionResource(resource_type, resource_id),
        operation,
    )
    return build_approval_service(db).request(
        request,
        payload,
        requested_by="local-user",
        ttl_seconds=300,
    )


def consume_api_approval(
    db: Session,
    approval_id: str,
    access: AccessContext,
    resource_type: ResourceType,
    resource_id: str,
    operation: PermissionOperation,
    payload: dict,
) -> None:
    approval = ApprovalRepository(db).get(approval_id)
    if approval is None:
        raise HTTPException(status_code=409, detail="A valid owner approval is required.")
    approval_context = AccessContext(
        subject=access.subject,
        scope=access.scope,
        request_id=approval.request_id,
    )
    request = approval_context.build_request(
        PermissionResource(resource_type, resource_id),
        operation,
    )
    consumed = build_approval_service(db).consume(approval_id, request, payload)
    if consumed is None:
        raise HTTPException(status_code=409, detail="Approval is invalid, expired, mismatched, or already consumed.")


@app.get("/api/permissions/grants")
async def list_permission_grants(
    limit: int = 100,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ, db)
    try:
        grants = PermissionRepository(db).list_recent(limit=limit)
        return {"grants": [serialize_grant(item) for item in grants]}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/permissions/grants")
async def create_permission_grant(
    data: PermissionGrantCreateRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    now = datetime.now(timezone.utc)
    if data.expires_at is not None and data.expires_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="expires_at must include a timezone.")
    try:
        grant = PermissionGrant(
            grant_id=str(uuid4()),
            subject=PermissionSubject(data.subject_type, data.subject_id),
            resource=PermissionResource(data.resource_type, data.resource_id),
            operation=data.operation,
            scope=PermissionScope(data.scope_type, data.scope_id, data.owner_id),
            issued_by="local-user",
            created_at=now,
            expires_at=data.expires_at,
            requires_approval=data.requires_approval,
        )
        manager = build_admin_permission_manager(db)
        issued = manager.issue_grant(
            grant,
            issuer=PermissionSubject(SubjectType.USER, "local-user"),
        )
        try:
            build_audit_service(db).record(
                event_type="permission_grant_issued",
                request_id=access.request_id,
                outcome="issued",
                subject=issued.subject,
                resource=issued.resource,
                operation=issued.operation,
                metadata={"grant_id": issued.grant_id, "status": "active"},
            )
        except Exception:
            manager.revoke_grant(issued.grant_id, issuer=PermissionSubject(SubjectType.USER, "local-user"))
            raise
        return serialize_grant(issued)
    except PermissionManagementDeniedError as exc:
        raise HTTPException(status_code=403, detail="Grant administration is not authorized for this scope or resource.") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/permissions/grants/{grant_id}")
async def revoke_permission_grant(
    grant_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    manager = build_admin_permission_manager(db)
    actor = PermissionSubject(SubjectType.USER, "local-user")
    try:
        revoked = manager.revoke_grant(grant_id, issuer=actor)
    except PermissionManagementDeniedError as exc:
        raise HTTPException(status_code=403, detail="Grant revocation is not authorized.") from exc
    if revoked is None:
        raise HTTPException(status_code=404, detail="Permission grant not found.")
    build_audit_service(db).record(
        event_type="permission_grant_revoked",
        request_id=access.request_id,
        outcome="revoked",
        subject=revoked.subject,
        resource=revoked.resource,
        operation=revoked.operation,
        metadata={"grant_id": revoked.grant_id, "status": "revoked"},
    )
    return serialize_grant(revoked)


@app.get("/api/permissions/approvals")
async def list_permission_approvals(
    status: ApprovalStatus | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ, db)
    try:
        items = ApprovalRepository(db).list_recent(limit=limit, status=status)
        return {"approvals": [serialize_approval(item) for item in items]}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/permissions/approvals/{approval_id}/approve")
async def approve_permission_request(
    approval_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    try:
        result = build_approval_service(db).approve(
            approval_id,
            approver=PermissionSubject(SubjectType.USER, "local-user"),
        )
        return serialize_approval(result)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval request not found.") from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail="Approval decision is not authorized.") from exc
    except ApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/permissions/approvals/{approval_id}/reject")
async def reject_permission_request(
    approval_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    try:
        result = build_approval_service(db).reject(
            approval_id,
            approver=PermissionSubject(SubjectType.USER, "local-user"),
        )
        return serialize_approval(result)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval request not found.") from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail="Approval decision is not authorized.") from exc
    except ApprovalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/permissions/audit")
async def list_permission_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ, db)
    try:
        return {"events": AuditRepository(db).list_recent(limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/permissions/approvals/session-delete/{session_id}")
async def request_session_delete_approval(
    session_id: int,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    return serialize_approval(create_api_approval(
        db, access, ResourceType.CONVERSATION, str(session_id), PermissionOperation.DELETE,
        {"action": "delete_session", "session_id": session_id},
    ))


@app.post("/api/permissions/approvals/avatar-delete")
async def request_avatar_delete_approval(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    return serialize_approval(create_api_approval(
        db, access, ResourceType.PROFILE, "local-user", PermissionOperation.DELETE,
        {"action": "delete_profile_avatar", "profile_id": "local-user"},
    ))


@app.post("/api/permissions/approvals/runtime-shutdown/{runtime_id}")
async def request_runtime_shutdown_approval(
    runtime_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    return serialize_approval(create_api_approval(
        db, access, ResourceType.RUNTIME, runtime_id, PermissionOperation.ADMINISTER,
        {"action": "runtime_shutdown", "runtime_id": runtime_id},
    ))


@app.get("/api/knowledge/search")
async def search_knowledge(
    query: str,
    scope_type: str,
    scope_id: str,
    owner_id: str = "local-user",
    limit: int = 10,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    try:
        results = build_knowledge_service(db, access).search(
            KnowledgeScope(scope_type, scope_id, owner_id),
            query,
            limit=limit,
        )
        return {"results": [item.__dict__ for item in results]}
    except KnowledgeAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="Knowledge access denied.") from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/knowledge/sources")
async def create_knowledge_source(
    data: KnowledgeSourceCreateRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    try:
        source = build_knowledge_service(db, access).create_source(
            KnowledgeScope(data.scope_type, data.scope_id, data.owner_id),
            source_type=data.source_type,
            title=data.title,
            uri=data.uri,
        )
        return {"source_id": source.id, "title": source.title, "scope_id": source.scope_id, "version": source.version, "status": source.status}
    except KnowledgeAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="Knowledge access denied.") from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/knowledge/sources/{source_id}/index")
async def index_knowledge_source(
    source_id: str,
    data: KnowledgeIndexRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    try:
        count = build_knowledge_service(db, access).index_extracted_text(
            KnowledgeScope(data.scope_type, data.scope_id, data.owner_id),
            source_id,
            data.extracted_text,
            extractor=data.extractor,
            extractor_version=data.extractor_version,
        )
        return {"source_id": source_id, "indexed_chunks": count}
    except KnowledgeAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="Knowledge access denied.") from exc
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Knowledge source not found.") from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def build_agent_services(db: Session):
    return agent_container.build_services(db)


def serialize_agent_definition(definition) -> dict:
    return {
        "agent_id": definition.agent_id,
        "version": definition.version,
        "goal": definition.goal,
        "description": definition.description,
        "completion": {
            "kind": definition.completion.kind,
            "description": definition.completion.description,
            "min_results": definition.completion.min_results,
        },
        "budgets": {
            "max_iterations": definition.budgets.max_iterations,
            "deadline_seconds": definition.budgets.deadline_seconds,
            "max_tool_calls": definition.budgets.max_tool_calls,
            "max_model_tokens": definition.budgets.max_model_tokens,
            "max_input_bytes": definition.budgets.max_input_bytes,
            "max_output_bytes": definition.budgets.max_output_bytes,
        },
        "allowed_tools": list(definition.allowed_tools),
        "allowed_models": list(definition.allowed_models),
        "data_scopes": list(definition.data_scopes),
        "approval_policy": definition.approval_policy,
        "enabled": definition.enabled,
    }


def serialize_agent_run(run) -> dict:
    return {
        "run_id": run.run_id,
        "task_id": run.task_id,
        "agent_id": run.agent_id,
        "agent_version": run.agent_version,
        "status": run.status.value,
        "attempt": run.attempt,
        "iteration": run.iteration,
        "tool_calls": run.tool_calls,
        "model_tokens": run.model_tokens,
        "pending_approval_id": run.pending_approval_id,
        "stop_reason": run.stop_reason.value if run.stop_reason else None,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "outcome": run.outcome,
        "version": run.version,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def serialize_agent_run_event(event) -> dict:
    # list_for_run returns redacted event mappings; event records are
    # attribute-like. Accept both shapes without exposing extra fields.
    if isinstance(event, dict):
        created_at = event.get("created_at")
        return {
            "event_type": event.get("event_type"),
            "outcome": event.get("outcome"),
            "metadata": dict(event.get("metadata") or {}),
            "created_at": created_at.isoformat() if created_at else None,
        }
    return {
        "event_type": event.event_type,
        "outcome": event.outcome,
        "metadata": dict(event.metadata or {}),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@app.get("/api/agents")
async def list_agent_definitions(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ, db)
    return {"agents": [serialize_agent_definition(item) for item in AgentDefinitionRepository(db).list_all()]}


@app.get("/api/agents/runs")
async def list_agent_runs(limit: int = 50, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ, db)
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200.")
    runs = AgentRunRepository(db).list_recent(limit=limit)
    return {"runs": [serialize_agent_run(item) for item in runs]}


@app.get("/api/agents/runs/{run_id}")
async def get_agent_run(run_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ, db)
    services = build_agent_services(db)
    try:
        run = services.lifecycle.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent run not found.") from exc
    events = AgentRunEventRepository(db).list_for_run(run_id, limit=100)
    # Run events carry redacted, whitelisted metadata only; raw prompts and
    # tool outputs are never part of the API surface.
    return {"run": serialize_agent_run(run), "events": [serialize_agent_run_event(item) for item in events]}


@app.post("/api/agents/tasks")
async def create_agent_task(data: AgentTaskCreateRequest, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    services = build_agent_services(db)
    try:
        scope = DataScope(
            domain="knowledge",
            scope_type=data.scope_type,
            scope_id=data.scope_id,
            owner_id=data.owner_id,
        )
        task = services.lifecycle.create_task(
            agent_id=data.agent_id,
            agent_version=data.agent_version,
            owner_id=data.owner_id,
            title=data.title,
            payload={"query": data.query},
            data_scopes=(scope,),
        )
        run = services.lifecycle.create_run(task.task_id)
    except AgentDefinitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"task_id": task.task_id, "run": serialize_agent_run(run)}


@app.post("/api/agents/runs/{run_id}/execute")
async def execute_agent_run(run_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    services = build_agent_services(db)
    try:
        run = await services.controller.execute(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent run not found.") from exc
    except AgentConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentControllerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentScopeDeniedError as exc:
        raise HTTPException(status_code=403, detail="Agent scope access denied.") from exc
    return {"run": serialize_agent_run(run)}


@app.post("/api/agents/runs/{run_id}/pause")
async def pause_agent_run(run_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    services = build_agent_services(db)
    try:
        current = services.lifecycle.get_run(run_id)
        run = services.lifecycle.pause(run_id, expected_version=current.version, reason=StopReason.PAUSED_BY_REQUEST)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent run not found.") from exc
    except (AgentTransitionError, AgentConcurrencyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": serialize_agent_run(run)}


@app.post("/api/agents/runs/{run_id}/resume")
async def resume_agent_run(run_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    """Clear a decided approval handoff; execution still goes through execute."""
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    services = build_agent_services(db)
    try:
        run = services.lifecycle.get_run(run_id)
        if run.pending_approval_id:
            approval = ApprovalRepository(db).get(run.pending_approval_id)
            if approval is None or approval.status not in {ApprovalStatus.APPROVED, ApprovalStatus.EXPIRED}:
                if approval is not None and approval.status is ApprovalStatus.REJECTED:
                    run = services.lifecycle.cancel(run_id, expected_version=run.version, reason="approval_rejected")
                    return {"run": serialize_agent_run(run)}
                raise HTTPException(status_code=409, detail="The pending approval must be decided first.")
            services.lifecycle.clear_pending_approval(run_id, expected_version=run.version)
        run = services.lifecycle.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent run not found.") from exc
    except (AgentTransitionError, AgentConcurrencyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": serialize_agent_run(run)}


@app.post("/api/agents/runs/{run_id}/cancel")
async def cancel_agent_run(run_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE, db)
    services = build_agent_services(db)
    try:
        current = services.lifecycle.get_run(run_id)
        run = services.lifecycle.cancel(run_id, expected_version=current.version)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent run not found.") from exc
    except (AgentTransitionError, AgentConcurrencyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": serialize_agent_run(run)}


@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")


@app.get("/api/settings")
async def get_settings(access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.READ)
    return ConfigManager.public_config()


@app.post("/api/settings")
async def update_settings(data: Dict[str, Any], access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.CONFIGURATION, "application-settings", PermissionOperation.UPDATE)
    try:
        updated = ConfigManager.update_config(data)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "success", "config": ConfigManager.public_config(updated)}


@app.get("/api/profile")
async def get_profile(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    return ProfileService(db, permission_manager, access, build_audit_service(db)).serialize()


@app.patch("/api/profile")
async def update_profile(data: ProfileUpdate, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    try:
        return ProfileService(db, permission_manager, access, build_audit_service(db)).update(data.display_name, data.username, data.email)
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put("/api/profile/avatar")
async def upload_profile_avatar(request: Request, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    try:
        result = ProfileService(db, permission_manager, access, build_audit_service(db)).set_avatar(await request.body())
        return {"status": "success", **result}
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/profile/avatar")
async def get_profile_avatar(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    try:
        content, media_type = ProfileService(db, permission_manager, access, build_audit_service(db)).get_avatar()
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/api/profile/avatar")
async def delete_profile_avatar(approval_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    consume_api_approval(
        db, approval_id, access, ResourceType.PROFILE, "local-user", PermissionOperation.DELETE,
        {"action": "delete_profile_avatar", "profile_id": "local-user"},
    )
    try:
        return {"status": "success", **ProfileService(db, permission_manager, access, build_audit_service(db)).delete_avatar()}
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/providers")
async def list_providers(access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.PROVIDER, "provider-collection", PermissionOperation.READ)
    return interface_manager.list_providers()


@app.get("/api/providers/{provider_id}/capabilities")
async def provider_capabilities(provider_id: str, access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.READ)
    try:
        return interface_manager.get_capabilities(provider_id)
    except InterfaceManagerError as exc:
        status_code = 404 if exc.category == "unknown_provider" else 502
        raise HTTPException(status_code=status_code, detail=exc.safe_message) from exc


@app.get("/api/providers/{provider_id}/catalog")
async def provider_catalog(provider_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    """Return repository-owned operator metadata and persisted catalog data without network I/O."""
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.READ, db)
    owns_session = not isinstance(db, Session)
    if owns_session:
        db = SessionLocal()
    try:
        try:
            result = interface_manager.get_provider_catalog(provider_id)
        except InterfaceManagerError as exc:
            status_code = 404 if exc.category == "unknown_provider" else 502
            raise HTTPException(status_code=status_code, detail=exc.safe_message) from exc
        snapshot = get_provider_catalog_snapshot(db, provider_id)
        result["storage"] = snapshot
        result["live_models"] = snapshot["live_models"]
        result["curated_models"] = snapshot["curated_models"]
        result["provider_runtime"] = snapshot["provider_runtime"]
        result["quota_snapshot"] = snapshot["quota"]
        result["sync_history"] = snapshot["sync_history"]
        return result
    finally:
        if owns_session:
            db.close()


@app.get("/api/providers/{provider_id}/models")
async def list_provider_models(provider_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    """Read the last successfully synchronized model IDs from SQLite; never performs network I/O."""
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.READ, db)
    try:
        operator_catalog = interface_manager.get_provider_catalog(provider_id).get("operator", {})
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404, detail=exc.safe_message) from exc
    snapshot = get_provider_catalog_snapshot(db, provider_id)
    active_models = [row["model_id"] for row in snapshot["live_models"] if row["active"]]
    # Router aliases are operator-level selectors, not concrete live model IDs.
    selectable_models = list(dict.fromkeys([*operator_catalog.get("router_aliases", []), *active_models]))
    return {"provider": provider_id, "models": selectable_models, "live_models": active_models, "source": "persistent_catalog"}


@app.post("/api/providers/{provider_id}/catalog/sync")
async def sync_provider_catalog(provider_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    """Refresh provider runtime, model inventory, and intelligence report."""
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.EXECUTE, db)
    try:
        result = await refresh_provider_intelligence(
            db, interface_manager, provider_id, ConfigManager.load_config
        )
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404 if exc.category == "unknown_provider" else 502, detail=exc.safe_message) from exc
    snapshot = get_provider_catalog_snapshot(db, provider_id)
    sync_result = result.get("catalog_sync") or {
        "status": "failed",
        "error": (result.get("error") or {}).get("message", "Provider catalog is unavailable."),
    }
    return {
        "sync": sync_result,
        "connection": result,
        "catalog": snapshot,
        "report": result.get("intelligence_report"),
    }


@app.get("/api/operational-report")
async def operational_report(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.PROVIDER, "provider-collection", PermissionOperation.READ, db)
    return get_operational_report(db)


@app.get("/api/intelligence/reports/latest")
async def latest_intelligence_report(
    provider_id: str,
    report_type: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.READ, db)
    try:
        interface_manager.get_provider_catalog(provider_id)
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404, detail=exc.safe_message) from exc
    report = get_latest_intelligence_report(db, provider_id, report_type)
    if report is None:
        raise HTTPException(status_code=404, detail="No intelligence report has been generated for this provider yet.")
    return report


@app.post("/api/intelligence/reports/offline")
async def generate_offline_intelligence_report(
    provider_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.EXECUTE, db)
    try:
        interface_manager.get_provider_catalog(provider_id)
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404, detail=exc.safe_message) from exc
    return create_offline_intelligence_report(db, provider_id)


@app.get("/api/providers/{provider_id}/quota")
async def provider_quota_status(provider_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.EXECUTE, db)
    try:
        status = await interface_manager.get_quota_status(provider_id)
        record_quota_snapshot(db, provider_id, status)
        return status
    except InterfaceManagerError as exc:
        status_code = 404 if exc.category == "unknown_provider" else 502
        raise HTTPException(status_code=status_code, detail=exc.safe_message) from exc


@app.post("/api/providers/{provider_id}/connection")
async def provider_connection_status(
    provider_id: str,
    response: Response,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_local_access_context),
):
    authorize_local_api_access(access, ResourceType.PROVIDER, provider_id, PermissionOperation.EXECUTE, db)
    # Connection checks may start a local runtime, discover models, and persist reports.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    try:
        return await refresh_provider_intelligence(
            db, interface_manager, provider_id, ConfigManager.load_config
        )
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404 if exc.category == "unknown_provider" else 502, detail=exc.safe_message) from exc


@app.get("/api/runtime/{runtime_id}/status")
async def get_local_runtime_status(runtime_id: str, access: AccessContext = Depends(get_local_access_context)):
    """Read runtime readiness without starting a local process."""
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.READ)
    try:
        return await runtime_manager.ensure_runtime(runtime_id, auto_start=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/{runtime_id}/snapshot")
async def get_local_runtime_snapshot(runtime_id: str, access: AccessContext = Depends(get_local_access_context)):
    """Return one read-only runtime-health and model-inventory snapshot."""
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.READ)
    try:
        return await runtime_monitor.snapshot(runtime_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/{runtime_id}/models")
async def get_local_runtime_models(runtime_id: str, access: AccessContext = Depends(get_local_access_context)):
    """Read installed/loaded model state without starting a local process."""
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.READ)
    try:
        return await runtime_manager.list_models(runtime_id, refresh=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/{runtime_id}/models/{model_id:path}")
async def get_local_runtime_model(runtime_id: str, model_id: str, access: AccessContext = Depends(get_local_access_context)):
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.READ)
    try:
        return await runtime_manager.inspect_model(runtime_id, model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runtime/{runtime_id}/models/{model_id:path}/load")
async def load_local_runtime_model(runtime_id: str, model_id: str, data: RuntimeLoadRequest, access: AccessContext = Depends(get_local_access_context)):
    """Explicitly load a model; this may start Ollama when configured to do so."""
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.EXECUTE)
    try:
        config = ConfigManager.load_config() or {}
        ollama_config = (config.get("providers_config") or {}).get("ollama", {})
        return await runtime_manager.load_model(
            runtime_id,
            model_id,
            options={"keep_alive": data.keep_alive},
            auto_start=bool(ollama_config.get("auto_start", True)),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runtime/{runtime_id}/models/{model_id:path}/unload")
async def unload_local_runtime_model(runtime_id: str, model_id: str, access: AccessContext = Depends(get_local_access_context)):
    """Explicitly unload a model; never stops the Ollama server process."""
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.EXECUTE)
    try:
        return await runtime_manager.unload_model(runtime_id, model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runtime/{runtime_id}/shutdown")
async def shutdown_local_runtime(runtime_id: str, approval_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    """Stop only an application-owned runtime process after explicit owner approval."""
    consume_api_approval(
        db, approval_id, access, ResourceType.RUNTIME, runtime_id, PermissionOperation.ADMINISTER,
        {"action": "runtime_shutdown", "runtime_id": runtime_id},
    )
    authorize_local_api_access(access, ResourceType.RUNTIME, runtime_id, PermissionOperation.ADMINISTER)
    try:
        results = await runtime_manager.shutdown(runtime_id)
        return results[0] if results else {"ok": True, "runtime_id": runtime_id, "state": "stopped"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions")
async def get_sessions(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    return ConversationService(db, permission_manager, access, build_audit_service(db)).list_sessions()


@app.post("/api/sessions")
async def create_session(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    return ConversationService(db, permission_manager, access, build_audit_service(db)).create_session()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int, approval_id: str, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    consume_api_approval(
        db, approval_id, access, ResourceType.CONVERSATION, str(session_id), PermissionOperation.DELETE,
        {"action": "delete_session", "session_id": session_id},
    )
    try:
        return ConversationService(db, permission_manager, access, build_audit_service(db)).delete_session(session_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: int, data: SessionTitleUpdate, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    try:
        return ConversationService(db, permission_manager, access, build_audit_service(db)).rename_session(session_id, data.title)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: int, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    try:
        return ConversationService(db, permission_manager, access, build_audit_service(db)).get_messages(session_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    conversation_service = ConversationService(db, permission_manager, access, build_audit_service(db))
    try:
        conversation_service.prepare_chat(req.session_id, req.message)
        context_package = ContextManager(conversation_service).assemble(
            ContextRequest(
                conversation_id=req.session_id,
                query=req.message,
                owner_id=access.scope.owner_id,
                history_limit=20,
                memory_scopes=(),
            )
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    history = [
        {"role": item.role or "user", "content": item.content}
        for item in context_package.items
    ]
    try:
        orchestrator = Orchestrator()
        provider_id = orchestrator.get_provider_id()
        formatted_messages, selected_model = orchestrator.build_messages(history, req.message)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def response_generator():
        full_response = ""
        yield f"data: {json.dumps({'type': 'meta', 'model': selected_model})}\n\n"
        try:
            async for chunk in interface_manager.stream_chat(
                provider_id, formatted_messages, model=selected_model
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception as exc:
            diagnostic_db = SessionLocal()
            try:
                record_model_runtime(
                    diagnostic_db,
                    provider_id,
                    selected_model,
                    "error",
                    {"category": getattr(exc, "category", "inference_failed"), "message": "Inference request failed."},
                )
            finally:
                diagnostic_db.close()
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
            return
        db_session = SessionLocal()
        try:
            record_model_runtime(db_session, provider_id, selected_model, "available")
            ConversationService(db_session, permission_manager, access, build_audit_service(db_session)).append_assistant_message(
                req.session_id, full_response, selected_model
            )
        finally:
            db_session.close()
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(response_generator(), media_type="text/event-stream")
