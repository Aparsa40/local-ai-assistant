# pyright: reportMissingImports=false
from datetime import datetime
from pathlib import Path

try:
    from sqlalchemy import (
        Boolean,
        Column,
        DateTime,
        ForeignKey,
        Integer,
        LargeBinary,
        String,
        Text,
        create_engine,
        inspect,
        text,
    )
    from sqlalchemy.orm import declarative_base, relationship, sessionmaker
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
    title_is_custom = Column(Boolean, nullable=False, default=False, server_default="0")
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


class UserProfile(Base):
    __tablename__ = "user_profile"
    id = Column(Integer, primary_key=True, default=1)
    display_name = Column(String(100), nullable=False, default="کاربر")
    username = Column(String(50), nullable=False, default="user")
    email = Column(String(254), nullable=False, default="")
    avatar_data = Column(LargeBinary, nullable=True)
    avatar_mime = Column(String(50), nullable=True)


def init_db():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # create_all does not add columns to existing SQLite tables; migrate this field safely.
    columns = {column["name"] for column in inspect(engine).get_columns("sessions")}
    if "title_is_custom" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE sessions ADD COLUMN title_is_custom BOOLEAN NOT NULL DEFAULT 0")
            )
