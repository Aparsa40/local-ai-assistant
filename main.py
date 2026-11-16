# pyright: reportMissingImports=false
from fastapi import FastAPI, Depends, HTTPException  # type: ignore[reportMissingImports]
from fastapi.staticfiles import StaticFiles  # type: ignore[reportMissingImports]
from fastapi.responses import StreamingResponse, FileResponse  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any
import json

from core.database import init_db, SessionLocal, ChatSession, ChatMessage
from core.config_manager import ConfigManager
from core.orchestrator import Orchestrator

app = FastAPI(title="Local Modular AI Assistant")
init_db()

# سرو کردن فایل‌های استاتیک رابط کاربری
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

@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")

@app.get("/api/settings")
async def get_settings():
    return ConfigManager.load_config()

@app.post("/api/settings")
async def update_settings(data: Dict[str, Any]):
    updated = ConfigManager.update_config(data)
    return {"status": "success", "config": updated}

@app.get("/api/sessions")
async def get_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()
    return [{"id": s.id, "title": s.title} for s in sessions]

@app.post("/api/sessions")
async def create_session(db: Session = Depends(get_db)):
    new_session = ChatSession(title="گفتگوی جدید")
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return {"id": new_session.id, "title": new_session.title}

@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: int, db: Session = Depends(get_db)):
    msgs = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).all()
    return [{"role": m.role, "content": m.content, "model": m.model_used} for m in msgs]

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="نشست یافت نشد")

    # به‌روزرسانی عنوان چت اگر اولین پیام است
    if session.title == "گفتگوی جدید":
        session.title = req.message[:35] + ("..." if len(req.message) > 35 else "")
        db.commit()

    # ذخیره پیام کاربر در دیتابیس
    user_msg = ChatMessage(session_id=req.session_id, role="user", content=req.message)
    db.add(user_msg)
    db.commit()

    # دریافت تاریخچه قبلی
    past_msgs = db.query(ChatMessage).filter(ChatMessage.session_id == req.session_id).all()
    history = [{"role": m.role, "content": m.content} for m in past_msgs[:-1]]

    orchestrator = Orchestrator()
    provider = orchestrator.get_provider()
    formatted_messages, selected_model = orchestrator.build_messages(history, req.message)

    async def response_generator():
        full_response = ""
        # ارسال متادیتا در خط اول برای نمایش مدل انتخاب‌شده در UI
        yield f"data: {json.dumps({'type': 'meta', 'model': selected_model})}\n\n"

        try:
            async for chunk in provider.chat_stream(formatted_messages, model=selected_model):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        # ذخیره پاسخ کامل مدل در دیتابیس
        db_session = SessionLocal()
        ai_msg = ChatMessage(
            session_id=req.session_id,
            role="assistant",
            content=full_response,
            model_used=selected_model
        )
        db_session.add(ai_msg)
        db_session.commit()
        db_session.close()

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(response_generator(), media_type="text/event-stream")