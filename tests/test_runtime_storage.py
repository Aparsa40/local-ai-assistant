import asyncio
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, LiveModelCatalogEntry, ProviderRuntimeStatus
from core.runtime.contracts import ModelObservation, ModelState, RuntimeProbe, RuntimeState
from core.runtime.storage import persist_runtime_snapshot


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def test_runtime_snapshot_persists_installed_and_loaded_states():
    engine, sessions = _db()
    db = sessions()
    try:
        probe = RuntimeProbe(
            runtime_id="ollama",
            state=RuntimeState.READY,
            endpoint_scope="local",
            checked_at="2026-11-23T10:00:00+00:00",
            already_running=True,
        )
        installed = [
            ModelObservation(
                runtime_id="ollama",
                model_id="llama3.2:1b",
                state=ModelState.INSTALLED,
                installed=True,
                source="ollama_api_tags",
            )
        ]
        loaded = [
            ModelObservation(
                runtime_id="ollama",
                model_id="llama3.2:1b",
                state=ModelState.LOADED,
                loaded=True,
                source="ollama_api_ps",
            )
        ]

        persist_runtime_snapshot(db, probe, installed, loaded)

        runtime = db.get(ProviderRuntimeStatus, "ollama")
        model = db.get(LiveModelCatalogEntry, ("ollama", "llama3.2:1b"))
        assert runtime.status == "reachable"
        assert runtime.probe == "local_model_runtime"
        assert runtime.runtime_details["already_running"] is True
        assert model.catalog_data["runtime_observation"]["installed"] is True
        assert model.catalog_data["runtime_observation"]["loaded"] is True
    finally:
        db.close()
        engine.dispose()


def test_unknown_loaded_telemetry_is_not_persisted_as_not_loaded():
    engine, sessions = _db()
    db = sessions()
    try:
        probe = RuntimeProbe(
            runtime_id="ollama",
            state=RuntimeState.READY,
            endpoint_scope="local",
        )
        installed = [
            ModelObservation(
                runtime_id="ollama",
                model_id="qwen2.5:3b",
                state=ModelState.INSTALLED,
                installed=True,
                source="ollama_api_tags",
            )
        ]

        persist_runtime_snapshot(db, probe, installed, None)

        model = db.get(LiveModelCatalogEntry, ("ollama", "qwen2.5:3b"))
        observation = model.catalog_data["runtime_observation"]
        assert observation["installed"] is True
        assert observation["loaded"] is None
        assert observation["loaded_source"] == "unknown"
    finally:
        db.close()
        engine.dispose()


def test_empty_loaded_snapshot_marks_installed_model_not_loaded():
    engine, sessions = _db()
    db = sessions()
    try:
        probe = RuntimeProbe(
            runtime_id="ollama",
            state=RuntimeState.READY,
            endpoint_scope="local",
        )
        installed = [
            ModelObservation(
                runtime_id="ollama",
                model_id="llama3.2:1b",
                state=ModelState.INSTALLED,
                installed=True,
                source="ollama_api_tags",
            )
        ]

        persist_runtime_snapshot(db, probe, installed, [])

        model = db.get(LiveModelCatalogEntry, ("ollama", "llama3.2:1b"))
        assert model.catalog_data["runtime_observation"]["loaded"] is False
    finally:
        db.close()
        engine.dispose()
