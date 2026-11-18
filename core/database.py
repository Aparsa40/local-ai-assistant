# pyright: reportMissingImports=false
from datetime import datetime
from pathlib import Path

try:
    from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
    from sqlalchemy.orm import declarative_base, sessionmaker, relationship
except ImportError as exc:
    raise ImportError("SQLAlchemy is required. Install it with: pip install sqlalchemy") from exc

DATABASE_PATH = Path("data/chat_history.db")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ChatSession(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), default="گفتگوی جدید")
    created_at = Column(DateTime, default=datetime.utcnow)
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    role = Column(String(50))
    content = Column(Text)
    model_used = Column(String(100), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    session = relationship("ChatSession", back_populates="messages")


def init_db():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
