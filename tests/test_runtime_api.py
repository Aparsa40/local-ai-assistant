import pytest
from fastapi.testclient import TestClient

import main
from core.runtime.monitor import RuntimeMonitor


class StubRuntimeManager:
    def __init__(self, runtime_ok=True):
        self.runtime_ok = runtime_ok
        self.ensure_calls = []
        self.inventory_calls = []

    async def ensure_runtime(self, runtime_id, auto_start=True):
        self.ensure_calls.append((runtime_id, auto_start))
        if not self.runtime_ok:
            return {
                "ok": False,
                "runtime_id": runtime_id,
                "state": "unavailable",
                "error": {"category": "runtime_unavailable"},
            }
        return {"ok": True, "runtime_id": runtime_id, "state": "ready"}

    async def list_models(self, runtime_id, refresh=True):
        self.inventory_calls.append((runtime_id, refresh))
        return {
            "ok": True,
            "runtime_id": runtime_id,
            "state": "ready",
            "data": {"models": [{"model_id": "llama3.2:1b", "installed": True, "loaded": False}]},
        }


@pytest.fixture
def runtime_client(monkeypatch):
    manager = StubRuntimeManager()
    monkeypatch.setattr(main, "runtime_monitor", RuntimeMonitor(manager))
    with TestClient(main.app) as client:
        yield client, manager


def test_runtime_snapshot_is_read_only_and_combines_inventory(runtime_client):
    client, manager = runtime_client

    response = client.get("/api/runtime/ollama/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["healthy"] is True
    assert payload["runtime"]["state"] == "ready"
    assert payload["models"][0]["model_id"] == "llama3.2:1b"
    assert manager.ensure_calls == [("ollama", False)]
    assert manager.inventory_calls == [("ollama", False)]


def test_runtime_snapshot_skips_inventory_when_runtime_is_unavailable(monkeypatch):
    manager = StubRuntimeManager(runtime_ok=False)
    monkeypatch.setattr(main, "runtime_monitor", RuntimeMonitor(manager))

    with TestClient(main.app) as client:
        response = client.get("/api/runtime/ollama/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["healthy"] is False
    assert payload["models"] == []
    assert payload["runtime"]["state"] == "unavailable"
    assert manager.ensure_calls == [("ollama", False)]
    assert manager.inventory_calls == []
