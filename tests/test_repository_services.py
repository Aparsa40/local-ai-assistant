from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.repositories import (
    CatalogRepository,
    MessageRepository,
    ProfileRepository,
    RuntimeRepository,
    SessionRepository,
)
from core.runtime.repository import RuntimeRepository as LegacyRuntimeRepository


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def test_catalog_repository_preserves_last_known_good_empty_sync_behavior():
    engine, factory = make_session_factory()
    db = factory()
    try:
        repository = CatalogRepository(db)
        repository.seed_operator_catalogs()
        repository.sync_live_models("ollama", ["llama3.2:1b"])
        result = repository.sync_live_models("ollama", [])
        snapshot = repository.get_provider_catalog_snapshot("ollama")

        assert result["status"] == "empty_response_preserved"
        assert [row["model_id"] for row in snapshot["live_models"] if row["active"]] == ["llama3.2:1b"]
        assert any(row["status"] == "empty_response_preserved" for row in snapshot["sync_history"])
    finally:
        db.close()
        engine.dispose()


def test_profile_repository_get_or_create_and_update():
    engine, factory = make_session_factory()
    db = factory()
    try:
        repository = ProfileRepository(db)
        profile = repository.get_or_create()
        profile.display_name = "Amir"
        repository.save(profile)

        assert repository.get_or_create().display_name == "Amir"
    finally:
        db.close()
        engine.dispose()


def test_session_repository_crud_and_custom_title():
    engine, factory = make_session_factory()
    db = factory()
    try:
        repository = SessionRepository(db)
        session = repository.create()
        renamed = repository.rename(session, "Architecture review")

        assert renamed.title == "Architecture review"
        assert renamed.title_is_custom is True
        assert repository.get(session.id).title == "Architecture review"
        assert repository.list_recent()[0].id == session.id

        repository.delete(session)
        assert repository.get(session.id) is None
    finally:
        db.close()
        engine.dispose()


def test_message_repository_appends_and_returns_stable_order():
    engine, factory = make_session_factory()
    db = factory()
    try:
        session = SessionRepository(db).create()
        repository = MessageRepository(db)
        first = repository.append(session.id, "user", "hello")
        second = repository.append(session.id, "assistant", "hi", model_used="test-model")

        messages = repository.list_for_session(session.id)
        assert [item.id for item in messages] == [first.id, second.id]
        assert messages[1].model_used == "test-model"
    finally:
        db.close()
        engine.dispose()


def test_runtime_repository_keeps_legacy_import_path():
    assert RuntimeRepository is LegacyRuntimeRepository
