import asyncio

import httpx
import pytest

from core.runtime import RuntimeManager
from core.runtime.adapters.ollama import OllamaRuntimeAdapter
from core.runtime.contracts import ModelState, RuntimeState
from core.runtime.errors import RuntimeNotRegisteredError


class FakeController:
    def __init__(self, result=None):
        self.result = result or {
            "status": "ready",
            "endpoint_scope": "local",
            "already_running": True,
            "started_by_application": False,
            "error": None,
        }
        self.calls = []

    async def ensure_running(self, endpoint, auto_start=True):
        self.calls.append((endpoint, auto_start))
        return self.result


def test_runtime_manager_reports_existing_ollama_server_without_starting():
    controller = FakeController()
    adapter = OllamaRuntimeAdapter(controller=controller)
    manager = RuntimeManager({"ollama": adapter})

    result = asyncio.run(manager.ensure_ready("ollama", auto_start=False))

    assert result.state is RuntimeState.READY
    assert result.already_running is True
    assert controller.calls == [("http://localhost:11434", False)]


def test_runtime_manager_never_enables_remote_autostart():
    controller = FakeController({
        "status": "unavailable",
        "endpoint_scope": "remote",
        "already_running": False,
        "started_by_application": False,
        "error": {"category": "remote_endpoint_unreachable", "message": "unavailable"},
    })
    adapter = OllamaRuntimeAdapter(
        base_url="https://ollama.example.test:11434", controller=controller
    )
    manager = RuntimeManager({"ollama": adapter})

    result = asyncio.run(manager.ensure_ready("ollama", auto_start=True))

    assert result.state is RuntimeState.UNAVAILABLE
    assert controller.calls[0][1] is False


def test_ollama_installed_models_are_independent_of_loaded_telemetry():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={
                "models": [{"name": "llama3.2:1b", "size": 1234, "digest": "abc"}]
            })
        if request.url.path == "/api/ps":
            return httpx.Response(503, json={"error": "telemetry unavailable"})
        return httpx.Response(404)

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    adapter = OllamaRuntimeAdapter(client_factory=client_factory)
    manager = RuntimeManager({"ollama": adapter})

    installed = asyncio.run(manager.list_installed_models("ollama"))
    loaded = asyncio.run(manager.list_loaded_models("ollama"))

    assert installed[0].model_id == "llama3.2:1b"
    assert installed[0].installed is True
    assert installed[0].loaded is None
    assert loaded is None
    assert calls == ["/api/tags", "/api/ps"]


def test_ollama_loaded_models_are_reported_as_loaded_without_inference():
    def handler(request):
        return httpx.Response(200, json={
            "models": [{"name": "qwen2.5:3b", "size_vram": 9876}]
        })

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    adapter = OllamaRuntimeAdapter(client_factory=client_factory)
    loaded = asyncio.run(adapter.list_loaded_models())

    assert loaded[0].model_id == "qwen2.5:3b"
    assert loaded[0].state is ModelState.LOADED
    assert loaded[0].loaded is True


def test_runtime_manager_rejects_unknown_runtime():
    manager = RuntimeManager()

    with pytest.raises(RuntimeNotRegisteredError) as exc:
        asyncio.run(manager.probe("missing"))

    assert exc.value.category == "runtime_not_registered"


def test_ollama_endpoint_rejects_embedded_credentials_and_bad_schemes():
    with pytest.raises(ValueError):
        OllamaRuntimeAdapter("http://user:pass@localhost:11434")
    with pytest.raises(ValueError):
        OllamaRuntimeAdapter("file:///tmp/ollama")


def test_runtime_manager_timeout_is_normalized():
    class HangingAdapter:
        runtime_id = "hang"

        async def probe(self):
            await asyncio.sleep(0.05)

        async def ensure_ready(self, auto_start=False):
            await asyncio.sleep(0.05)

        async def list_installed_models(self):
            return []

        async def list_loaded_models(self):
            return []

        async def close(self):
            return None

    manager = RuntimeManager({"hang": HangingAdapter()}, operation_timeout=0.001)
    with pytest.raises(Exception) as exc:
        asyncio.run(manager.probe("hang"))

    assert getattr(exc.value, "category", None) == "runtime_request_timeout"
