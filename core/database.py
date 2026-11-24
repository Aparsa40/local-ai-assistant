# pyright: reportMissingImports=false
from datetime import datetime, timezone
from pathlib import Path

try:
    from sqlalchemy import (
        Boolean, Column, DateTime, ForeignKey, Integer, JSON, LargeBinary,
        String, Text, inspect, text,
    )
    from sqlalchemy.orm import declarative_base, relationship
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


from .storage.manager import get_storage_manager

# Compatibility exports remain available while application callers migrate to StorageManager.
storage_manager = get_storage_manager()
DATABASE_URL = storage_manager.config.database_url
DATABASE_PATH = storage_manager.config.database_path or Path("data/chat_history.db")
engine = storage_manager.engine
SessionLocal = storage_manager.session_factory
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


class RuntimeStatus(Base):
    """Latest observed status for one local runtime adapter."""
    __tablename__ = "runtime_statuses"
    runtime_id = Column(String(80), primary_key=True)
    state = Column(String(40), nullable=False, default="unknown")
    endpoint_scope = Column(String(40), nullable=True)
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
    """Create missing ORM tables, then apply ordered, versioned schema migrations."""
    from .migrations import run_migrations

    run_migrations(engine)
    Base.metadata.create_all(bind=engine)


class MemoryRecord(Base):
    """Scoped, provenance-aware memory candidate and lifecycle record."""

    __tablename__ = "memories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_type = Column(String(20), nullable=False, index=True)
    content = Column(Text, nullable=False)
    dedup_key = Column(String(255), nullable=True, index=True)
    scope_type = Column(String(40), nullable=False, index=True)
    scope_id = Column(String(160), nullable=False, index=True)
    owner_id = Column(String(160), nullable=False, default="local")
    source_type = Column(String(40), nullable=False)
    source_ref = Column(String(255), nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    confidence = Column(Integer, nullable=False, default=50)
    importance = Column(Integer, nullable=False, default=50)
    status = Column(String(20), nullable=False, default="candidate", index=True)
    verified_by = Column(String(160), nullable=True)
    retention_days = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    superseded_by_id = Column(Integer, ForeignKey("memories.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)
    last_accessed_at = Column(DateTime, nullable=True)



class PermissionGrantRecord(Base):
    """Persisted exact-scope authorization grant; no wildcard semantics are supported."""

    __tablename__ = "permission_grants"
    grant_id = Column(String(80), primary_key=True)
    subject_type = Column(String(40), nullable=False, index=True)
    subject_id = Column(String(160), nullable=False, index=True)
    resource_type = Column(String(60), nullable=False, index=True)
    resource_id = Column(String(255), nullable=False, index=True)
    operation = Column(String(40), nullable=False, index=True)
    scope_type = Column(String(40), nullable=False, index=True)
    scope_id = Column(String(160), nullable=False, index=True)
    owner_id = Column(String(160), nullable=False, index=True)
    issued_by = Column(String(160), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    expires_at = Column(DateTime, nullable=True, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    requires_approval = Column(Boolean, nullable=False, default=False)
    conditions = Column(JSON, nullable=False, default=dict)



class PermissionApprovalRecord(Base):
    """One-time approval bound to a specific request and action digest."""

    __tablename__ = "permission_approvals"
    approval_id = Column(String(80), primary_key=True)
    request_id = Column(String(80), nullable=False, index=True)
    action_hash = Column(String(64), nullable=False)
    subject_type = Column(String(40), nullable=False)
    subject_id = Column(String(160), nullable=False)
    resource_type = Column(String(60), nullable=False)
    resource_id = Column(String(255), nullable=False)
    operation = Column(String(40), nullable=False)
    scope_type = Column(String(40), nullable=False)
    scope_id = Column(String(160), nullable=False)
    owner_id = Column(String(160), nullable=False)
    requested_by = Column(String(160), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    decided_by = Column(String(160), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)


class PermissionAuditEventRecord(Base):
    """Append-only redacted authorization and tool execution audit event."""

    __tablename__ = "permission_audit_events"
    event_id = Column(String(80), primary_key=True)
    event_type = Column(String(80), nullable=False, index=True)
    request_id = Column(String(80), nullable=False, index=True)
    subject_type = Column(String(40), nullable=True)
    subject_id = Column(String(160), nullable=True)
    resource_type = Column(String(60), nullable=True)
    resource_id = Column(String(255), nullable=True)
    operation = Column(String(40), nullable=True)
    outcome = Column(String(40), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)


# Register Knowledge ORM tables on every database import before metadata.create_all().
from .knowledge import models as _knowledge_models  # noqa: E402,F401
