import asyncio
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import provider_intelligence
from core.catalog_storage import (
    get_latest_intelligence_report,
    get_provider_catalog_snapshot,
    seed_operator_catalogs,
    sync_live_models,
)
from core.database import Base
from core.provider_intelligence import (
    LocalRuntimeController,
    build_offline_report,
    create_offline_intelligence_report,
    refresh_provider_intelligence,
)


def test_local_runtime_reuses_an_existing_ollama_server(monkeypatch):
    async def probe(_url):
        return True

    monkeypatch.setattr(LocalRuntimeController, "_probe", staticmethod(probe))
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )

    result = asyncio.run(LocalRuntimeController().ensure_running("http://localhost:11434"))

    assert result["status"] == "ready"
    assert result["already_running"] is True
    assert result["started_by_application"] is False


def test_remote_ollama_endpoint_is_never_started_locally(monkeypatch):
    async def probe(_url):
        return False

    monkeypatch.setattr(LocalRuntimeController, "_probe", staticmethod(probe))
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("remote endpoint must not spawn")),
    )

    result = asyncio.run(LocalRuntimeController().ensure_running("http://192.0.2.10:11434"))

    assert result["status"] == "unavailable"
    assert result["endpoint_scope"] == "remote"
    assert result["error"]["category"] == "remote_endpoint_unreachable"


def test_local_runtime_respects_disabled_auto_start(monkeypatch):
    async def probe(_url):
        return False

    monkeypatch.setattr(LocalRuntimeController, "_probe", staticmethod(probe))
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("auto-start disabled")),
    )

    result = asyncio.run(
        LocalRuntimeController().ensure_running("http://127.0.0.1:11434", auto_start=False)
    )

    assert result["error"]["category"] == "auto_start_disabled"


def test_local_runtime_reports_missing_ollama_executable(monkeypatch):
    async def probe(_url):
        return False

    monkeypatch.setattr(LocalRuntimeController, "_probe", staticmethod(probe))
    monkeypatch.setattr(LocalRuntimeController, "_find_executable", staticmethod(lambda: None))

    result = asyncio.run(LocalRuntimeController().ensure_running("http://localhost:11434"))

    assert result["status"] == "not_installed"
    assert result["error"]["category"] == "ollama_not_installed"


def test_local_runtime_starts_ollama_and_waits_until_ready(monkeypatch):
    probes = iter([False, False, True])

    async def probe(_url):
        return next(probes)

    async def no_wait(_seconds):
        return None

    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    calls = []
    monkeypatch.setattr(LocalRuntimeController, "_probe", staticmethod(probe))
    monkeypatch.setattr(LocalRuntimeController, "_find_executable", staticmethod(lambda: "ollama"))
    monkeypatch.setattr(provider_intelligence.asyncio, "sleep", no_wait)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or FakeProcess(),
    )

    result = asyncio.run(
        LocalRuntimeController(startup_timeout=1).ensure_running("http://localhost:11434")
    )

    assert result["status"] == "ready"
    assert result["started_by_application"] is True
    assert result["process_id"] == 4321
    assert calls[0][0] == ["ollama", "serve"]
    assert calls[0][1]["shell"] is False


def test_local_runtime_startup_timeout_is_reported(monkeypatch):
    async def probe(_url):
        return False

    async def no_wait(_seconds):
        return None

    class FakeProcess:
        pid = 4322

        def poll(self):
            return None

    monkeypatch.setattr(LocalRuntimeController, "_probe", staticmethod(probe))
    monkeypatch.setattr(LocalRuntimeController, "_find_executable", staticmethod(lambda: "ollama"))
    monkeypatch.setattr(provider_intelligence.asyncio, "sleep", no_wait)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = asyncio.run(
        LocalRuntimeController(startup_timeout=0).ensure_running("http://localhost:11434")
    )

    assert result["status"] == "starting_timeout"
    assert result["error"]["category"] == "startup_timeout"


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def test_runtime_refresh_persists_ollama_metadata_and_report(monkeypatch):
    engine, session_factory = _database()
    db = session_factory()
    try:
        seed_operator_catalogs(db)

        async def ensure_running(self, base_url, auto_start=True):
            return {
                "status": "ready",
                "endpoint_scope": "local",
                "already_running": False,
                "started_by_application": True,
                "error": None,
            }

        monkeypatch.setattr(
            LocalRuntimeController,
            "ensure_running",
            ensure_running,
        )

        class FakeInterfaceManager:
            async def check_connection(self, provider_id):
                return {
                    "provider": provider_id,
                    "status": "reachable",
                    "probe": "model_catalog",
                    "model_count": 1,
                    "models": ["llama3.2:1b"],
                    "checked_at": "2026-11-22T12:00:00+00:00",
                    "error": None,
                }

            async def get_model_metadata(self, provider_id, model_ids):
                return {
                    "models": {
                        "llama3.2:1b": {
                            "details": {"family": "llama", "parameter_size": "1B"},
                            "capabilities": ["tools"],
                            "context_length": 8192,
                        }
                    },
                    "errors": [],
                }

            def get_provider_catalog(self, provider_id):
                return {"operator": {}}

        result = asyncio.run(
            refresh_provider_intelligence(
                db,
                FakeInterfaceManager(),
                "ollama",
                lambda: {"providers_config": {"ollama": {"base_url": "http://localhost:11434", "auto_start": True}}},
            )
        )

        snapshot = get_provider_catalog_snapshot(db, "ollama")
        model = snapshot["live_models"][0]
        assert result["status"] == "reachable"
        assert model["catalog_data"]["details"]["parameter_size"] == "1B"
        assert result["intelligence_report"]["overall_status"] == "healthy"
        assert get_latest_intelligence_report(db, "ollama", "runtime")["models"][0]["model_id"] == "llama3.2:1b"
    finally:
        db.close()
        engine.dispose()


def test_offline_report_uses_only_persisted_data(monkeypatch):
    engine, session_factory = _database()
    db = session_factory()
    try:
        seed_operator_catalogs(db)
        sync_live_models(
            db,
            "ollama",
            ["llama3.2:1b"],
            model_metadata={
                "llama3.2:1b": {
                    "details": {"family": "llama"},
                    "capabilities": ["tools"],
                }
            },
        )

        def unexpected_io(*args, **kwargs):
            raise AssertionError("offline report must not perform network or process I/O")

        monkeypatch.setattr("httpx.AsyncClient", unexpected_io)
        monkeypatch.setattr(subprocess, "Popen", unexpected_io)

        report = create_offline_intelligence_report(db, "ollama")

        assert report["report_type"] == "offline"
        assert report["models"][0]["model_id"] == "llama3.2:1b"
        assert report["models"][0]["task_suitability"][-1]["suitability"] == "supported"
        assert get_latest_intelligence_report(db, "ollama", "offline")["report_type"] == "offline"
    finally:
        db.close()
        engine.dispose()


def test_offline_report_marks_missing_observations_unknown():
    engine, session_factory = _database()
    db = session_factory()
    try:
        seed_operator_catalogs(db)
        report = build_offline_report(db, "ollama")
        assert report["freshness"]["status"] == "unknown"
        assert report["source_snapshot_at"] is None
        assert "does not verify current provider reachability" in report["limitations"][0]
    finally:
        db.close()
        engine.dispose()
