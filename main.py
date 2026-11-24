# pyright: reportMissingImports=false
import ipaddress
import json
from uuid import uuid4
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.config_manager import ConfigManager
from core.database import init_db
from core.conversations import ConversationNotFoundError, ConversationService
from core.profiles import ProfileService, ProfileServiceError
from core.storage.manager import get_storage_manager
from core.permissions.audit import AuditService
from core.permissions.guards import AccessDeniedError
from core.permissions.local_policy import LocalApplicationPolicy
from core.permissions.manager import PermissionManager
from core.permissions.types import AccessContext, PermissionScope, PermissionSubject, ScopeType, SubjectType
from core.repositories.audit_repository import AuditRepository
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
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_db():
    with storage_manager.session() as db:
        yield db


def get_local_access_context(request: Request) -> AccessContext:
    """Resolve the fixed local principal only for loopback clients."""
    client_host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(client_host)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Local access only.") from exc
    if not address.is_loopback and not (address.ipv4_mapped and address.ipv4_mapped.is_loopback):
        raise HTTPException(status_code=403, detail="Local access only.")
    return AccessContext(
        subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
        scope=PermissionScope(ScopeType.LOCAL, "local-machine", "local-user"),
        request_id=str(uuid4()),
    )


def build_audit_service(db: Session) -> AuditService:
    return AuditService(AuditRepository(db))


@app.exception_handler(AccessDeniedError)
async def handle_access_denied(request: Request, exc: AccessDeniedError):
    return JSONResponse(status_code=403, content={"detail": "Access denied."})


class ChatRequest(BaseModel):
    session_id: int
    message: str


class SessionTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=254)


class RuntimeLoadRequest(BaseModel):
    keep_alive: str | int = "5m"


@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")


@app.get("/api/settings")
async def get_settings():
    return ConfigManager.public_config()


@app.post("/api/settings")
async def update_settings(data: Dict[str, Any]):
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
async def delete_profile_avatar(db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
    try:
        return {"status": "success", **ProfileService(db, permission_manager, access, build_audit_service(db)).delete_avatar()}
    except ProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/providers")
async def list_providers():
    return interface_manager.list_providers()


@app.get("/api/providers/{provider_id}/capabilities")
async def provider_capabilities(provider_id: str):
    try:
        return interface_manager.get_capabilities(provider_id)
    except InterfaceManagerError as exc:
        status_code = 404 if exc.category == "unknown_provider" else 502
        raise HTTPException(status_code=status_code, detail=exc.safe_message) from exc


@app.get("/api/providers/{provider_id}/catalog")
async def provider_catalog(provider_id: str, db: Session = Depends(get_db)):
    """Return repository-owned operator metadata and persisted catalog data without network I/O."""
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
async def list_provider_models(provider_id: str, db: Session = Depends(get_db)):
    """Read the last successfully synchronized model IDs from SQLite; never performs network I/O."""
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
async def sync_provider_catalog(provider_id: str, db: Session = Depends(get_db)):
    """Refresh provider runtime, model inventory, and intelligence report."""
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
async def operational_report(db: Session = Depends(get_db)):
    return get_operational_report(db)


@app.get("/api/intelligence/reports/latest")
async def latest_intelligence_report(
    provider_id: str,
    report_type: str | None = None,
    db: Session = Depends(get_db),
):
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
):
    try:
        interface_manager.get_provider_catalog(provider_id)
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404, detail=exc.safe_message) from exc
    return create_offline_intelligence_report(db, provider_id)


@app.get("/api/providers/{provider_id}/quota")
async def provider_quota_status(provider_id: str, db: Session = Depends(get_db)):
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
):
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
async def get_local_runtime_status(runtime_id: str):
    """Read runtime readiness without starting a local process."""
    try:
        return await runtime_manager.ensure_runtime(runtime_id, auto_start=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/{runtime_id}/snapshot")
async def get_local_runtime_snapshot(runtime_id: str):
    """Return one read-only runtime-health and model-inventory snapshot."""
    try:
        return await runtime_monitor.snapshot(runtime_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/{runtime_id}/models")
async def get_local_runtime_models(runtime_id: str):
    """Read installed/loaded model state without starting a local process."""
    try:
        return await runtime_manager.list_models(runtime_id, refresh=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/{runtime_id}/models/{model_id:path}")
async def get_local_runtime_model(runtime_id: str, model_id: str):
    try:
        return await runtime_manager.inspect_model(runtime_id, model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runtime/{runtime_id}/models/{model_id:path}/load")
async def load_local_runtime_model(runtime_id: str, model_id: str, data: RuntimeLoadRequest):
    """Explicitly load a model; this may start Ollama when configured to do so."""
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
async def unload_local_runtime_model(runtime_id: str, model_id: str):
    """Explicitly unload a model; never stops the Ollama server process."""
    try:
        return await runtime_manager.unload_model(runtime_id, model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runtime/{runtime_id}/shutdown")
async def shutdown_local_runtime(runtime_id: str):
    """Stop only a runtime process explicitly owned by this application."""
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
async def delete_session(session_id: int, db: Session = Depends(get_db), access: AccessContext = Depends(get_local_access_context)):
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
    try:
        preparation = ConversationService(db, permission_manager, access, build_audit_service(db)).prepare_chat(req.session_id, req.message)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    history = [{"role": item.role, "content": item.content} for item in preparation.history]
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
