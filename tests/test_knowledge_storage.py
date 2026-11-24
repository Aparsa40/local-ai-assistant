from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.knowledge import (
    KnowledgeAccessDeniedError,
    KnowledgeScope,
    KnowledgeService,
    ManagedFileStorage,
)
from core.migrations import CURRENT_SCHEMA_REVISION, run_migrations


class AllowKnowledgeScope:
    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return scope_type == "user" and scope_id in {"profile-1", "profile-2"} and owner_id == "owner-a"


def make_service(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    assert run_migrations(engine) == CURRENT_SCHEMA_REVISION
    session = sessionmaker(bind=engine)()
    service = KnowledgeService(
        session,
        access_policy=AllowKnowledgeScope(),
        file_storage=ManagedFileStorage(tmp_path / "managed"),
    )
    return engine, session, service, KnowledgeScope("user", "profile-1", "owner-a")


def test_knowledge_storage_is_default_deny(tmp_path: Path):
    engine, session, _, scope = make_service(tmp_path)
    try:
        denied = KnowledgeService(session)
        with pytest.raises(KnowledgeAccessDeniedError):
            denied.create_source(scope, source_type="text", title="Private")
    finally:
        session.close()
        engine.dispose()


def test_source_indexing_lexical_search_and_revision_history(tmp_path: Path):
    engine, session, service, scope = make_service(tmp_path)
    try:
        source = service.create_source(scope, source_type="text", title="راهنمای پروژه")
        first_count = service.index_extracted_text(
            scope, source.id, "SQLite provides durable local storage. Knowledge retrieval uses lexical search.",
            chunk_size=100, overlap=10,
        )
        assert first_count >= 1
        results = service.search(scope, "durable storage")
        assert results
        assert results[0].source_id == source.id
        assert "durable" in results[0].content

        second_count = service.index_extracted_text(
            scope, source.id, "A revised document describes permission-aware Knowledge retrieval.",
            chunk_size=100, overlap=10,
        )
        assert second_count >= 1
        assert service.search(scope, "durable storage") == []
        assert service.search(scope, "permission-aware") 
        artifacts = session.execute(
            text("SELECT COUNT(*) FROM knowledge_artifacts WHERE source_id = :source_id"),
            {"source_id": source.id},
        ).scalar_one()
        assert artifacts == 2
        assert service.get_source(scope, source.id).version == 2
    finally:
        session.close()
        engine.dispose()


def test_search_isolated_by_owner_scope_and_archived_sources_are_hidden(tmp_path: Path):
    engine, session, service, scope = make_service(tmp_path)
    try:
        source = service.create_source(scope, source_type="text", title="Scoped note")
        service.index_extracted_text(scope, source.id, "Distinctive zebra knowledge token")
        other_scope = KnowledgeScope("user", "profile-2", "owner-a")
        assert service.search(other_scope, "zebra") == []
        archived = service.archive_source(scope, source.id)
        assert archived.status == "archived"
        assert service.search(scope, "zebra") == []
    finally:
        session.close()
        engine.dispose()


def test_original_files_are_stored_under_opaque_keys_and_read_only_in_scope(tmp_path: Path):
    engine, session, service, scope = make_service(tmp_path)
    try:
        source = service.create_source(scope, source_type="file", title="Source file")
        record = service.store_original_file(
            scope, source.id, filename="../../private.txt", content=b"original bytes", mime_type="text/plain"
        )
        assert record.original_filename == "private.txt"
        assert record.storage_key not in record.original_filename
        assert record.source_version == 1
        assert service.get_source(scope, source.id).version == 1
        assert service.read_original_file(scope, record.id) == b"original bytes"
        with pytest.raises(KnowledgeAccessDeniedError):
            service.read_original_file(KnowledgeScope("user", "other", "owner-a"), record.id)
    finally:
        session.close()
        engine.dispose()


def test_managed_file_storage_rejects_unsafe_keys_and_oversized_payloads(tmp_path: Path):
    storage = ManagedFileStorage(tmp_path / "files", max_bytes=4)
    with pytest.raises(ValueError):
        storage.store(b"too large")
    with pytest.raises(ValueError):
        storage.read("../escape")
    key, _, _ = storage.store(b"safe")
    assert storage.read(key) == b"safe"
    storage.delete(key)
    with pytest.raises(ValueError):
        storage.read(key)


def test_migrations_are_versioned_idempotent_and_upgrade_legacy_columns(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE sessions (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE provider_runtime_status (provider_id VARCHAR(80) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO sessions(id) VALUES (41)"))
            connection.execute(text("INSERT INTO provider_runtime_status(provider_id) VALUES ('ollama')"))
            # Bootstrap the ORM-owned tables while simulating a pre-migration legacy database.
            Base.metadata.create_all(bind=connection)
        assert run_migrations(engine) == CURRENT_SCHEMA_REVISION
        assert run_migrations(engine) == CURRENT_SCHEMA_REVISION
        assert "title_is_custom" in {c["name"] for c in inspect(engine).get_columns("sessions")}
        assert "runtime_details" in {c["name"] for c in inspect(engine).get_columns("provider_runtime_status")}
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id FROM sessions")).scalar_one() == 41
            assert connection.execute(text("SELECT provider_id FROM provider_runtime_status")).scalar_one() == "ollama"
        revisions = engine.connect().execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one()
        assert revisions == 3
    finally:
        engine.dispose()


def test_migrations_bootstrap_knowledge_schema_on_a_fresh_database():
    engine = create_engine("sqlite://")
    try:
        assert run_migrations(engine) == CURRENT_SCHEMA_REVISION
        tables = set(inspect(engine).get_table_names())
        assert {"schema_migrations", "knowledge_sources", "knowledge_files", "knowledge_chunks", "knowledge_artifacts"} <= tables
        with engine.connect() as connection:
            revisions = connection.execute(text("SELECT revision FROM schema_migrations ORDER BY revision")).scalars().all()
            assert revisions == ["0001_legacy_additive_columns", "0002_knowledge_fts", "0003_knowledge_file_versions"]
            assert connection.execute(text("SELECT COUNT(*) FROM knowledge_chunks_fts")).scalar_one() == 0
    finally:
        engine.dispose()
