# pyright: reportMissingImports=false
import json
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.config_manager import ConfigManager
from core.database import ChatMessage, ChatSession, SessionLocal, init_db
from core.orchestrator import Orchestrator
from core.providers.registry import PROVIDER_FACTORIES, get_provider_factory

app = FastAPI(title="Local Modular AI Assistant")
init_db()
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


@app.get("/api/providers")
async def list_providers():
    return [{"id": name, "name": name.replace("_", " ").title()} for name in PROVIDER_FACTORIES]


@app.get("/api/providers/{provider_id}/models")
async def list_provider_models(provider_id: str):
    if provider_id not in PROVIDER_FACTORIES:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_id}")
    config = ConfigManager.load_config().get("providers_config", {}).get(provider_id, {})
    try:
        provider = get_provider_factory(provider_id)(config)
        models = await provider.list_models()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"provider": provider_id, "models": models}


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


@app.patch("/api/sessions/{session_id}")
async def rename_session(
    session_id: int,
    data: SessionTitleUpdate,
    db: Session = Depends(get_db),
):
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
        provider = orchestrator.get_provider()
        formatted_messages, selected_model = orchestrator.build_messages(history, req.message)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def response_generator():
        full_response = ""
        yield f"data: {json.dumps({'type': 'meta', 'model': selected_model})}\n\n"
        try:
            async for chunk in provider.chat_stream(formatted_messages, model=selected_model):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
            return

        db_session = SessionLocal()
        try:
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
