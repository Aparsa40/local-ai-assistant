# pyright: reportMissingImports=false
import json
from io import BytesIO
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from PIL import Image, ImageOps, UnidentifiedImageError

from core.config_manager import ConfigManager
from core.database import ChatMessage, ChatSession, SessionLocal, UserProfile, init_db
from core.orchestrator import Orchestrator
from core.interface_manager import InterfaceManager, InterfaceManagerError
from core.catalog_storage import (
    get_operational_report,
    get_provider_catalog_snapshot,
    record_provider_runtime,
    record_model_runtime,
    record_quota_snapshot,
    record_sync_failure,
    seed_operator_catalogs,
    sync_live_models,
)

app = FastAPI(title="Local Modular AI Assistant")
interface_manager = InterfaceManager()
init_db()
with SessionLocal() as _catalog_seed_db:
    seed_operator_catalogs(_catalog_seed_db)
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChatRequest(BaseModel):
    session_id: int
    message: str


class SessionTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=254)


def get_or_create_profile(db: Session) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.id == 1).first()
    if profile is None:
        profile = UserProfile(id=1, display_name="کاربر", username="user", email="")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def serialize_profile(profile: UserProfile) -> Dict[str, Any]:
    return {
        "display_name": profile.display_name,
        "username": profile.username,
        "email": profile.email,
        "avatar_url": "/api/profile/avatar" if profile.avatar_data else "",
        "avatar_configured": bool(profile.avatar_data),
    }


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
async def get_profile(db: Session = Depends(get_db)):
    return serialize_profile(get_or_create_profile(db))


@app.patch("/api/profile")
async def update_profile(data: ProfileUpdate, db: Session = Depends(get_db)):
    display_name = data.display_name.strip()
    username = data.username.strip()
    email = data.email.strip()
    if not display_name or not username:
        raise HTTPException(status_code=422, detail="نام نمایشی و نام کاربری نمی‌توانند خالی باشند")
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        raise HTTPException(status_code=422, detail="فرمت ایمیل معتبر نیست")
    profile = get_or_create_profile(db)
    profile.display_name = display_name
    profile.username = username
    profile.email = email
    db.commit()
    db.refresh(profile)
    return serialize_profile(profile)


@app.put("/api/profile/avatar")
async def upload_profile_avatar(request: Request, db: Session = Depends(get_db)):
    image_bytes = await request.body()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="فایلی دریافت نشد")
    if len(image_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم تصویر نباید بیشتر از ۲ مگابایت باشد")
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise HTTPException(status_code=415, detail="فقط فرمت‌های PNG، JPG و WebP مجاز هستند")
            if source.width > 4096 or source.height > 4096:
                raise HTTPException(status_code=422, detail="ابعاد تصویر نباید از ۴۰۹۶×۴۰۹۶ پیکسل بیشتر باشد")
            source.load()
            normalized = ImageOps.fit(source.convert("RGB"), (256, 256))
            output = BytesIO()
            normalized.save(output, format="WEBP", quality=85, method=6)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail="فایل تصویر معتبر نیست") from exc
    profile = get_or_create_profile(db)
    profile.avatar_data = output.getvalue()
    profile.avatar_mime = "image/webp"
    db.commit()
    return {"status": "success", **serialize_profile(profile)}


@app.get("/api/profile/avatar")
async def get_profile_avatar(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    if not profile.avatar_data:
        raise HTTPException(status_code=404, detail="تصویر پروفایل ثبت نشده است")
    return Response(
        content=profile.avatar_data,
        media_type=profile.avatar_mime or "image/webp",
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/api/profile/avatar")
async def delete_profile_avatar(db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    profile.avatar_data = None
    profile.avatar_mime = None
    db.commit()
    return {"status": "success", **serialize_profile(profile)}


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
    """Explicitly refresh a provider catalog and persist it only after successful discovery."""
    try:
        model_ids = await interface_manager.list_models(provider_id)
        operator = interface_manager.get_provider_catalog(provider_id).get("operator", {})
        aliases = set(operator.get("router_aliases", []))
        exact_model_ids = [model_id for model_id in model_ids if model_id not in aliases]
        summary = sync_live_models(db, provider_id, exact_model_ids)
        return {"sync": summary, "catalog": get_provider_catalog_snapshot(db, provider_id)}
    except InterfaceManagerError as exc:
        record_sync_failure(db, provider_id, {"category": exc.category, "message": exc.safe_message})
        raise HTTPException(status_code=404 if exc.category == "unknown_provider" else 502, detail=exc.safe_message) from exc


@app.get("/api/operational-report")
async def operational_report(db: Session = Depends(get_db)):
    return get_operational_report(db)


@app.get("/api/providers/{provider_id}/quota")
async def provider_quota_status(provider_id: str, db: Session = Depends(get_db)):
    try:
        status = await interface_manager.get_quota_status(provider_id)
        record_quota_snapshot(db, provider_id, status)
        return status
    except InterfaceManagerError as exc:
        status_code = 404 if exc.category == "unknown_provider" else 502
        raise HTTPException(status_code=status_code, detail=exc.safe_message) from exc


@app.get("/api/providers/{provider_id}/connection")
async def provider_connection_status(provider_id: str, db: Session = Depends(get_db)):
    try:
        result = await interface_manager.check_connection(provider_id)
        model_ids = result.pop("models", [])
        record_provider_runtime(db, provider_id, result)
        if result.get("status") == "reachable":
            operator = interface_manager.get_provider_catalog(provider_id).get("operator", {})
            aliases = set(operator.get("router_aliases", []))
            exact_model_ids = [model_id for model_id in model_ids if model_id not in aliases]
            result["catalog_sync"] = sync_live_models(db, provider_id, exact_model_ids)
        return result
    except InterfaceManagerError as exc:
        raise HTTPException(status_code=404, detail=exc.safe_message) from exc


@app.get("/api/sessions")
async def get_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()
    return [{"id": session.id, "title": session.title} for session in sessions]


@app.post("/api/sessions")
async def create_session(db: Session = Depends(get_db)):
    new_session = ChatSession(title="گفتگوی جدید")
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return {"id": new_session.id, "title": new_session.title}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="نشست یافت نشد")
    db.delete(session)
    db.commit()
    return {"status": "success", "deleted_session_id": session_id}


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: int, data: SessionTitleUpdate, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="نشست یافت نشد")
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="عنوان نشست نمی‌تواند خالی باشد")
    session.title = title
    session.title_is_custom = True
    db.commit()
    db.refresh(session)
    return {"id": session.id, "title": session.title}


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="نشست یافت نشد")
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).all()
    return [{"role": message.role, "content": message.content, "model": message.model_used} for message in messages]


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="نشست یافت نشد")
    if session.title == "گفتگوی جدید" and not session.title_is_custom:
        session.title = req.message[:35] + ("..." if len(req.message) > 35 else "")
        db.commit()
    user_msg = ChatMessage(session_id=req.session_id, role="user", content=req.message)
    db.add(user_msg)
    db.commit()
    past_msgs = db.query(ChatMessage).filter(ChatMessage.session_id == req.session_id).all()
    history = [{"role": message.role, "content": message.content} for message in past_msgs[:-1]]
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
            db_session.add(ChatMessage(
                session_id=req.session_id,
                role="assistant",
                content=full_response,
                model_used=selected_model,
            ))
            db_session.commit()
        finally:
            db_session.close()
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(response_generator(), media_type="text/event-stream")
