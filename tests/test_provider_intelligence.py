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
    record_provider_runtime,
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
    async def probe(_url, **_kwargs):
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
        record_provider_runtime(
            db,
            "ollama",
            {
                "status": "reachable",
                "runtime": {"started_by_application": True, "process_id": 9876},
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
        assert report["provider_runtime"]["startup"]["started_by_application"] is True
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


def test_ollama_metadata_combines_tags_and_show_evidence(monkeypatch):
    import httpx
    from core.providers.ollama_provider import OllamaProvider

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={
                "models": [{
                    "name": "llama3.2:1b",
                    "size": 987654,
                    "digest": "abc123",
                    "modified_at": "2026-11-22T10:00:00Z",
                    "details": {
                        "family": "llama",
                        "parameter_size": "1B",
                        "quantization_level": "Q4_K_M",
                    },
                }]
            })
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:1b"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={
                "details": {
                    "format": "gguf",
                    "family": "llama",
                    "families": ["llama"],
                    "parameter_size": "1B",
                    "quantization_level": "Q4_K_M",
                },
                "capabilities": ["completion", "tools", "vision"],
                "model_info": {
                    "llama.context_length": 8192,
                    "llama.embedding_length": 2048,
                    "llama.vocab_size": 128256,
                },
                "template": "{{ .Prompt }}",
            })
        return httpx.Response(404)

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr("core.providers.ollama_provider.httpx.AsyncClient", client_factory)
    result = asyncio.run(
        OllamaProvider().list_model_metadata(["llama3.2:1b"])
    )
    metadata = result["models"]["llama3.2:1b"]
    assert metadata["size"] == 987654
    assert metadata["details"]["quantization_level"] == "Q4_K_M"
    assert metadata["context_length"] == 8192
    assert metadata["capabilities"] == ["completion", "tools", "vision"]
    assert metadata["runtime_observation"] == {
        "installed": True,
        "loaded": True,
        "loaded_source": "ollama_api_ps",
    }
    assert result["errors"] == []


def test_ollama_provider_normalizes_localhost_and_default_port():
    from core.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(base_url="http://localhost")
    assert provider.base_url == "http://127.0.0.1:11434"


def test_local_runtime_reuses_its_owned_process_after_startup_timeout(monkeypatch):
    probes = iter([False, False])

    async def probe(_url):
        return next(probes)

    async def no_wait(_seconds):
        return None

    class FakeProcess:
        pid = 4323

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

    controller = LocalRuntimeController(startup_timeout=0)
    first = asyncio.run(controller.ensure_running("http://localhost:11434"))
    second = asyncio.run(controller.ensure_running("http://localhost:11434"))

    assert first["error"]["category"] == "startup_timeout"
    assert second["error"]["category"] == "startup_timeout"
    assert len(calls) == 1
    assert calls[0][1]["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"


def test_runtime_report_marks_preserved_empty_catalog_as_degraded():
    engine, session_factory = _database()
    db = session_factory()
    try:
        seed_operator_catalogs(db)
        sync_live_models(db, "ollama", ["llama3.2:1b"])
        report = provider_intelligence.build_runtime_report(
            db,
            "ollama",
            {
                "status": "reachable",
                "catalog_sync": {"status": "empty_response_preserved"},
            },
        )
        assert report["overall_status"] == "degraded"
        assert any("last-known-good" in warning for warning in report["warnings"])
        assert report["models"][0]["model_id"] == "llama3.2:1b"
    finally:
        db.close()
        engine.dispose()



def test_embedding_model_is_not_classified_as_a_chat_model():
    assessment = {
        item["task"]: item
        for item in provider_intelligence._model_task_assessments({
            "catalog_data": {
                "capabilities": ["embedding"],
                "details": {"family": "nomic-bert"},
            },
            "operator_profile": {},
        })
    }

    assert assessment["embeddings"]["suitability"] == "supported"
    assert assessment["general_chat"]["suitability"] == "unknown"
    assert assessment["tool_calling"]["suitability"] == "unknown"


def test_model_name_alone_does_not_prove_coding_or_tool_calling():
    assessment = {
        item["task"]: item
        for item in provider_intelligence._model_task_assessments({
            "catalog_data": {"capabilities": ["completion"]},
            "operator_profile": {},
        })
    }

    assert assessment["general_chat"]["suitability"] == "likely"
    assert assessment["coding"]["suitability"] == "unknown"
    assert assessment["tool_calling"]["suitability"] == "unknown"


def test_report_fingerprint_ignores_volatile_last_seen_timestamps():
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
                    "size": 1234,
                    "digest": "stable-digest",
                    "capabilities": ["completion", "tools"],
                    "details": {"family": "llama"},
                }
            },
        )
        first = provider_intelligence.build_runtime_report(
            db, "ollama", {"status": "reachable", "catalog_sync": {"status": "success"}}
        )
        sync_live_models(
            db,
            "ollama",
            ["llama3.2:1b"],
            model_metadata={
                "llama3.2:1b": {
                    "size": 1234,
                    "digest": "stable-digest",
                    "capabilities": ["completion", "tools"],
                    "details": {"family": "llama"},
                }
            },
        )
        second = provider_intelligence.build_runtime_report(
            db, "ollama", {"status": "reachable", "catalog_sync": {"status": "success"}}
        )
        assert first["fingerprint"] == second["fingerprint"]
    finally:
        db.close()
        engine.dispose()


def test_analyzed_model_exposes_roles_chat_eligibility_and_runtime_state():
    snapshot = {
        "live_models": [{
            "model_id": "nomic-embed-text:latest",
            "active": True,
            "source": "ollama_local_api",
            "catalog_data": {
                "capabilities": ["embedding"],
                "runtime_observation": {"installed": True, "loaded": False},
                "details": {"family": "nomic-bert"},
            },
            "runtime": {"availability": "unknown"},
        }],
    }
    model = provider_intelligence._analyze_snapshot(snapshot)[0]

    assert model["model_kind"] == "embedding"
    assert model["model_roles"] == ["embedding_indexer"]
    assert model["chat_eligible"] is False
    assert model["runtime"]["installed"] is True
    assert model["runtime"]["loaded"] is False



def test_remote_ollama_endpoint_retains_environment_proxy_support():
    from core.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(base_url="https://ollama.example.test:11434")
    assert provider._trust_env is True
    assert provider.base_url == "https://ollama.example.test:11434"



def test_local_runtime_shutdown_stops_only_application_owned_process():
    class FakeProcess:
        pid = 9876

        def __init__(self):
            self.terminated = False
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            return 0

    controller = LocalRuntimeController()
    process = FakeProcess()
    controller._owned_process = process
    controller._owned_endpoint = "http://127.0.0.1:11434"

    result = asyncio.run(controller.shutdown_owned_process())

    assert result["status"] == "stopped"
    assert result["process_stopped"] is True
    assert process.terminated is True
    assert process.killed is False
    assert controller._owned_process is None
    assert controller._owned_endpoint is None


def test_local_runtime_shutdown_does_not_touch_unowned_processes():
    controller = LocalRuntimeController()

    result = asyncio.run(controller.shutdown_owned_process())

    assert result["status"] == "stopped"
    assert result["process_stopped"] is False
    assert result["reason"] == "not_owned"
