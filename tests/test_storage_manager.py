from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from core.database import (
    Base,
    ChatMessage,
    ChatSession,
    OperatorCatalogEntry,
    RuntimeEvent,
    RuntimeStatus,
    UserProfile,
    init_db,
)
from core.storage.config import StorageConfig
from core.storage.exceptions import StorageConfigurationError
from core.storage.manager import StorageManager


def test_storage_manager_creates_sqlite_parent_directory_and_checks_health(tmp_path: Path):
    database_path = tmp_path / "nested" / "assistant.db"
    manager = StorageManager(StorageConfig(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        assert database_path.parent.is_dir()
        assert manager.health_check() == {"ok": True, "backend": "sqlite"}
    finally:
        manager.dispose()


def test_storage_manager_transaction_commits_on_success(tmp_path: Path):
    database_path = tmp_path / "transaction.db"
    manager = StorageManager(StorageConfig(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        with manager.engine.begin() as connection:
            connection.execute(text("CREATE TABLE checks (value INTEGER NOT NULL)"))

        with manager.transaction() as session:
            session.execute(text("INSERT INTO checks (value) VALUES (1)"))

        with manager.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM checks")) == 1
    finally:
        manager.dispose()


def test_storage_manager_transaction_rolls_back_on_error(tmp_path: Path):
    database_path = tmp_path / "rollback.db"
    manager = StorageManager(StorageConfig(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        with manager.engine.begin() as connection:
            connection.execute(text("CREATE TABLE checks (value INTEGER NOT NULL)"))

        with pytest.raises(RuntimeError, match="force rollback"):
            with manager.transaction() as session:
                session.execute(text("INSERT INTO checks (value) VALUES (1)"))
                raise RuntimeError("force rollback")

        with manager.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM checks")) == 0
    finally:
        manager.dispose()


def test_storage_manager_uses_one_connection_for_in_memory_sqlite():
    manager = StorageManager(StorageConfig(database_url="sqlite://"))
    try:
        with manager.engine.begin() as connection:
            connection.execute(text("CREATE TABLE checks (value INTEGER NOT NULL)"))
        with manager.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM checks")) == 0
    finally:
        manager.dispose()


def test_storage_manager_rejects_unimplemented_database_backends():
    with pytest.raises(StorageConfigurationError, match="Only SQLite is enabled"):
        StorageManager(StorageConfig(database_url="postgresql://localhost/assistant"))


def test_storage_manager_creates_the_current_orm_schema():
    manager = StorageManager(StorageConfig(database_url="sqlite://"))
    expected_tables = {
        "sessions",
        "messages",
        "memories",
        "user_profile",
        "operator_catalogs",
        "operator_model_profiles",
        "live_model_catalog",
        "provider_runtime_status",
        "model_runtime_status",
        "provider_quota_snapshots",
        "catalog_sync_history",
        "provider_intelligence_reports",
        "runtime_model_states",
        "runtime_statuses",
        "runtime_events",
        "permission_grants",
        "permission_approvals",
        "permission_audit_events",
        "knowledge_sources",
        "knowledge_files",
        "knowledge_chunks",
        "knowledge_artifacts",
        "agent_definitions",
        "agent_tasks",
        "agent_runs",
        "agent_run_events",
        "agent_checkpoints",
        "orchestration_goals",
        "orchestration_plans",
        "orchestration_nodes",
        "orchestration_dependencies",
        "orchestration_assignments",
        "orchestration_handoffs",
        "orchestration_events",
    }
    try:
        Base.metadata.create_all(bind=manager.engine)
        assert set(inspect(manager.engine).get_table_names()) == expected_tables
    finally:
        manager.dispose()



def test_init_db_migrates_then_bootstraps_and_uses_all_core_domains():
    manager = StorageManager(StorageConfig(database_url="sqlite://"))
    try:
        init_db(manager.engine)
        tables = set(inspect(manager.engine).get_table_names())
        assert {
            "schema_migrations",
            "sessions",
            "messages",
            "user_profile",
            "operator_catalogs",
            "runtime_statuses",
            "runtime_events",
            "knowledge_sources",
            "knowledge_files",
            "knowledge_chunks",
            "knowledge_artifacts",
            "agent_definitions",
            "agent_tasks",
            "agent_runs",
            "agent_run_events",
            "agent_checkpoints",
            "orchestration_goals",
            "orchestration_plans",
            "orchestration_nodes",
            "orchestration_dependencies",
            "orchestration_assignments",
            "orchestration_handoffs",
            "orchestration_events",
        } <= tables

        with manager.transaction() as session:
            chat = ChatSession(title="migration smoke")
            session.add(chat)
            session.flush()
            session.add(ChatMessage(session_id=chat.id, role="user", content="hello"))
            session.add(UserProfile(display_name="Test user", username="test", email=""))
            session.add(OperatorCatalogEntry(provider_id="test-provider", name="Test", manifest={}))
            session.add(RuntimeStatus(runtime_id="test-runtime", state="ready"))
            session.add(RuntimeEvent(
                runtime_id="test-runtime",
                event_type="smoke",
                state="ready",
                success=True,
                details={},
            ))

        with manager.session() as session:
            assert session.query(ChatSession).count() == 1
            assert session.query(ChatMessage).count() == 1
            assert session.query(UserProfile).count() == 1
            assert session.query(OperatorCatalogEntry).count() == 1
            assert session.query(RuntimeStatus).count() == 1
            assert session.query(RuntimeEvent).count() == 1
            revisions = session.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one()
            # Ordered revisions 0001..0006, including 0006_orchestration.
            assert revisions == 6
    finally:
        manager.dispose()
