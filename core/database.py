# pyright: reportMissingImports=false
from datetime import datetime, timezone
from pathlib import Path

try:
    from sqlalchemy import (
        Boolean, Column, DateTime, ForeignKey, Integer, JSON, LargeBinary,
        String, Text, create_engine, inspect, text,
    )
    from sqlalchemy.orm import declarative_base, relationship, sessionmaker
except ImportError as exc:
    raise ImportError("SQLAlchemy is required. Install it with: pip install sqlalchemy") from exc


def utcnow_naive() -> datetime:
    """Return the current UTC time as a naive datetime for SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(value: datetime) -> datetime:
    """Normalize a datetime to naive UTC; naive legacy values are already treated as UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


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
    created_at = Column(DateTime, default=utcnow_naive)
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    role = Column(String(50))
    content = Column(Text)
    model_used = Column(String(100), nullable=True)
    timestamp = Column(DateTime, default=utcnow_naive)
    session = relationship("ChatSession", back_populates="messages")


class UserProfile(Base):
    __tablename__ = "user_profile"
    id = Column(Integer, primary_key=True, default=1)
    display_name = Column(String(100), nullable=False, default="کاربر")
    username = Column(String(50), nullable=False, default="user")
    email = Column(String(254), nullable=False, default="")
    avatar_data = Column(LargeBinary, nullable=True)
    avatar_mime = Column(String(50), nullable=True)


class OperatorCatalogEntry(Base):
    __tablename__ = "operator_catalogs"
    provider_id = Column(String(80), primary_key=True)
    name = Column(String(160), nullable=False)
    manifest = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class OperatorModelProfile(Base):
    __tablename__ = "operator_model_profiles"
    provider_id = Column(String(80), primary_key=True)
    model_id = Column(String(255), primary_key=True)
    profile = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class LiveModelCatalogEntry(Base):
    __tablename__ = "live_model_catalog"
    provider_id = Column(String(80), primary_key=True)
    model_id = Column(String(255), primary_key=True)
    catalog_data = Column(JSON, nullable=False, default=dict)
    source = Column(String(80), nullable=False, default="provider_api")
    active = Column(Boolean, nullable=False, default=True)
    first_seen_at = Column(DateTime, nullable=False, default=utcnow_naive)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class ProviderRuntimeStatus(Base):
    __tablename__ = "provider_runtime_status"
    provider_id = Column(String(80), primary_key=True)
    status = Column(String(40), nullable=False, default="unknown")
    probe = Column(String(80), nullable=True)
    model_count = Column(Integer, nullable=True)
    checked_at = Column(DateTime, nullable=True)
    error = Column(JSON, nullable=True)
    runtime_details = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class ModelRuntimeStatus(Base):
    __tablename__ = "model_runtime_status"
    provider_id = Column(String(80), primary_key=True)
    model_id = Column(String(255), primary_key=True)
    availability = Column(String(40), nullable=False, default="unknown")
    last_successful_request = Column(DateTime, nullable=True)
    last_error = Column(JSON, nullable=True)
    observed_limits = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class ProviderQuotaSnapshot(Base):
    __tablename__ = "provider_quota_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(80), nullable=False, index=True)
    status = Column(JSON, nullable=False, default=dict)
    source = Column(String(160), nullable=True)
    observed_at = Column(DateTime, nullable=False, default=utcnow_naive)


class CatalogSyncHistory(Base):
    __tablename__ = "catalog_sync_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(80), nullable=False, index=True)
    status = Column(String(40), nullable=False)
    source = Column(String(80), nullable=False, default="provider_api")
    discovered_count = Column(Integer, nullable=False, default=0)
    added_count = Column(Integer, nullable=False, default=0)
    retired_count = Column(Integer, nullable=False, default=0)
    error = Column(JSON, nullable=True)
    synced_at = Column(DateTime, nullable=False, default=utcnow_naive)


class ProviderIntelligenceReport(Base):
    __tablename__ = "provider_intelligence_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(80), nullable=False, index=True)
    report_type = Column(String(20), nullable=False, index=True)
    generated_at = Column(DateTime, nullable=False, default=utcnow_naive)
    source_snapshot_at = Column(DateTime, nullable=True)
    overall_status = Column(String(40), nullable=False, default="unknown")
    summary = Column(Text, nullable=False, default="")
    report_data = Column(JSON, nullable=False, default=dict)
    schema_version = Column(Integer, nullable=False, default=1)


class RuntimeModelState(Base):
    """Latest observed lifecycle state, separate from inference availability."""
    __tablename__ = "runtime_model_states"
    runtime_id = Column(String(80), primary_key=True)
    model_id = Column(String(255), primary_key=True)
    state = Column(String(40), nullable=False, default="unknown")
    observed_at = Column(DateTime, nullable=False, default=utcnow_naive)
    details = Column(JSON, nullable=False, default=dict)
    error = Column(JSON, nullable=True)


class RuntimeEvent(Base):
    """Append-only local runtime lifecycle event."""
    __tablename__ = "runtime_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    runtime_id = Column(String(80), nullable=False, index=True)
    model_id = Column(String(255), nullable=True, index=True)
    event_type = Column(String(80), nullable=False)
    state = Column(String(40), nullable=False)
    success = Column(Boolean, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    error = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)


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

    runtime_columns = {column["name"] for column in inspect(engine).get_columns("provider_runtime_status")}
    if "runtime_details" not in runtime_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE provider_runtime_status ADD COLUMN runtime_details JSON")
            )
