import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, RuntimeEvent, RuntimeModelState, RuntimeStatus
from core.runtime.contracts import RuntimeAdapter, RuntimeResult
from core.runtime.manager import RuntimeManager
from core.runtime.model_lifecycle import ModelLifecycle
from core.runtime.ollama_adapter import OllamaRuntimeAdapter
from core.runtime.repository import RuntimeRepository
from core.runtime.resource_manager import ResourceManager


class FakeRuntimeAdapter(RuntimeAdapter):
    runtime_id = "fake"
    capabilities = frozenset({"model_inventory", "model_load", "model_unload"})

    def __init__(self, models=None):
        self.models = models or []
        self.ensure_calls = []
        self.load_calls = []
        self.unload_calls = []

    async def ensure_available(self, auto_start=True):
        self.ensure_calls.append(auto_start)
        return RuntimeResult(True, self.runtime_id, "ready", data={"endpoint_scope": "local"})

    async def list_models(self):
        return RuntimeResult(True, self.runtime_id, "ready", data={"models": self.models})

    async def inspect_model(self, model_id):
        model = next((item for item in self.models if item["model_id"] == model_id), None)
        if model is None:
            return RuntimeResult(False, self.runtime_id, "failed", model_id, error={"category": "model_not_found"})
        state = "loaded" if model.get("loaded") else "installed"
        return RuntimeResult(True, self.runtime_id, state, model_id, data=model)

    async def load_model(self, model_id, options=None):
        self.load_calls.append((model_id, options or {}))
        for model in self.models:
            if model["model_id"] == model_id:
                model["loaded"] = True
        return RuntimeResult(True, self.runtime_id, "loaded", model_id, data={"operation": "load"})

    async def unload_model(self, model_id):
        self.unload_calls.append(model_id)
        for model in self.models:
            if model["model_id"] == model_id:
                model["loaded"] = False
        return RuntimeResult(True, self.runtime_id, "installed", model_id, data={"operation": "unload"})

    async def shutdown_owned_process(self):
        return RuntimeResult(True, self.runtime_id, "stopped", data={"process_stopped": False})


class RuntimeManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_inventory_does_not_start_runtime(self):
        adapter = FakeRuntimeAdapter([{"model_id": "local-model", "loaded": False}])
        manager = RuntimeManager([adapter])

        result = await manager.list_models("fake", refresh=False)

        self.assertTrue(result["ok"])
        self.assertEqual(adapter.ensure_calls, [])

    async def test_load_ensures_runtime_and_loads_installed_model(self):
        adapter = FakeRuntimeAdapter([{"model_id": "local-model", "loaded": False}])
        manager = RuntimeManager([adapter])

        result = await manager.load_model("fake", "local-model", {"keep_alive": "10m"}, auto_start=False)

        self.assertTrue(result["ok"])
        self.assertEqual(adapter.ensure_calls, [False])
        self.assertEqual(adapter.load_calls, [("local-model", {"keep_alive": "10m"})])

    async def test_load_does_not_repeat_for_already_loaded_model(self):
        adapter = FakeRuntimeAdapter([{"model_id": "local-model", "loaded": True}])
        manager = RuntimeManager([adapter])

        result = await manager.load_model("fake", "local-model")

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["already_loaded"])
        self.assertEqual(adapter.load_calls, [])

    async def test_load_rejects_model_not_installed(self):
        adapter = FakeRuntimeAdapter([])
        manager = RuntimeManager([adapter])

        result = await manager.load_model("fake", "missing")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["category"], "model_not_installed")
        self.assertEqual(adapter.load_calls, [])

    async def test_resource_limit_prevents_another_model_load(self):
        adapter = FakeRuntimeAdapter([
            {"model_id": "already-loaded", "loaded": True},
            {"model_id": "next-model", "loaded": False},
        ])
        manager = RuntimeManager([adapter], resource_manager=ResourceManager(max_loaded_models=1))

        result = await manager.load_model("fake", "next-model")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["category"], "resource_limit_exceeded")
        self.assertEqual(adapter.load_calls, [])

    async def test_unload_uses_inspected_state_and_calls_adapter(self):
        adapter = FakeRuntimeAdapter([{"model_id": "local-model", "loaded": True}])
        manager = RuntimeManager([adapter])

        result = await manager.unload_model("fake", "local-model")

        self.assertTrue(result["ok"])
        self.assertEqual(adapter.unload_calls, ["local-model"])

    async def test_unload_is_idempotent_for_installed_model(self):
        adapter = FakeRuntimeAdapter([{"model_id": "local-model", "loaded": False}])
        manager = RuntimeManager([adapter])

        result = await manager.unload_model("fake", "local-model")

        self.assertTrue(result["ok"])
        self.assertEqual(adapter.unload_calls, [])

    async def test_adapter_timeout_returns_normalized_failure(self):
        class HangingAdapter(FakeRuntimeAdapter):
            async def ensure_available(self, auto_start=True):
                await asyncio.sleep(0.05)
                return await super().ensure_available(auto_start=auto_start)

        manager = RuntimeManager([HangingAdapter()], operation_timeout=0.005)
        result = await manager.ensure_runtime("fake")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["category"], "runtime_request_timeout")

    async def test_timeout_includes_waiting_for_concurrency_slot(self):
        class HangingAdapter(FakeRuntimeAdapter):
            def __init__(self):
                super().__init__()
                self.started = asyncio.Event()

            async def ensure_available(self, auto_start=True):
                self.ensure_calls.append(auto_start)
                self.started.set()
                await asyncio.sleep(0.5)
                return RuntimeResult(True, self.runtime_id, "ready")

        first = HangingAdapter()
        second = HangingAdapter()
        second.runtime_id = "second"
        manager = RuntimeManager(
            [first, second],
            operation_timeout=0.1,
            max_concurrent_operations=1,
        )

        first_task = asyncio.create_task(manager.ensure_runtime("fake"))
        await first.started.wait()
        second_result = await manager.ensure_runtime("second")
        first_result = await first_task

        self.assertEqual(first_result["error"]["category"], "runtime_request_timeout")
        self.assertEqual(second_result["error"]["category"], "runtime_request_timeout")
        # The second adapter times out in the queue and is never invoked.
        self.assertEqual(second.ensure_calls, [])

    async def test_invalid_adapter_result_is_normalized(self):
        class InvalidAdapter(FakeRuntimeAdapter):
            async def ensure_available(self, auto_start=True):
                return {"ok": True}

        result = await RuntimeManager([InvalidAdapter()]).ensure_runtime("fake")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["category"], "runtime_protocol_error")

    async def test_unknown_runtime_is_rejected(self):
        manager = RuntimeManager()
        with self.assertRaises(KeyError):
            await manager.ensure_runtime("missing")


class ModelLifecycleTests(unittest.TestCase):
    def test_valid_and_invalid_transitions(self):
        self.assertEqual(ModelLifecycle.transition("installed", "loading"), "loading")
        self.assertEqual(ModelLifecycle.transition("loading", "loaded"), "loaded")
        with self.assertRaises(ValueError):
            ModelLifecycle.transition("installed", "running")


class RuntimeRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.repository = RuntimeRepository(self.Session)

    def tearDown(self):
        self.engine.dispose()

    def test_runtime_and_model_snapshots_are_persisted_separately(self):
        runtime = RuntimeResult(
            True,
            "ollama",
            "ready",
            data={"endpoint_scope": "local", "version": "0.15.0"},
        )
        self.repository.record(runtime, "runtime_probe")
        self.repository.record(runtime, "runtime_probe")
        inventory = RuntimeResult(
            True,
            "ollama",
            "ready",
            data={"models": [
                {"model_id": "llama3.2:1b", "loaded": True, "installed": True},
                {"model_id": "qwen2.5:3b", "loaded": False, "installed": True},
            ]},
        )
        self.repository.record(inventory, "model_inventory")

        session = self.Session()
        try:
            runtime_row = session.get(RuntimeStatus, "ollama")
            self.assertEqual(runtime_row.state, "ready")
            self.assertEqual(runtime_row.endpoint_scope, "local")
            loaded = session.get(RuntimeModelState, ("ollama", "llama3.2:1b"))
            installed = session.get(RuntimeModelState, ("ollama", "qwen2.5:3b"))
            self.assertEqual(loaded.state, "loaded")
            self.assertEqual(installed.state, "installed")
            # Read-only inventory refreshes update snapshots, not an unbounded event log.
            self.assertEqual(session.query(RuntimeEvent).count(), 1)
        finally:
            session.close()

    def test_failed_operation_does_not_erase_last_known_model_state(self):
        observed = RuntimeResult(True, "ollama", "installed", "llama3.2:1b", data={"installed": True})
        failed = RuntimeResult(
            False,
            "ollama",
            "failed",
            "llama3.2:1b",
            error={"category": "load_failed", "message": "load failed"},
        )
        self.repository.record(observed, "model_inspection")
        self.repository.record(failed, "load_failed")

        session = self.Session()
        try:
            row = session.get(RuntimeModelState, ("ollama", "llama3.2:1b"))
            self.assertEqual(row.state, "installed")
            self.assertEqual(row.error["category"], "load_failed")
        finally:
            session.close()

    def test_failed_inventory_records_event_without_overwriting_runtime_status(self):
        ready = RuntimeResult(
            True, "ollama", "ready", data={"endpoint_scope": "local"}
        )
        failed_inventory = RuntimeResult(
            False,
            "ollama",
            "unavailable",
            error={"category": "model_inventory_unavailable", "message": "tags failed"},
        )
        self.repository.record(ready, "runtime_probe")
        self.repository.record(failed_inventory, "model_inventory_failed")

        session = self.Session()
        try:
            runtime_row = session.get(RuntimeStatus, "ollama")
            self.assertEqual(runtime_row.state, "ready")
            events = session.query(RuntimeEvent).filter_by(
                event_type="model_inventory_failed"
            ).all()
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0].success)
        finally:
            session.close()

    def test_model_lifecycle_event_is_recorded(self):
        result = RuntimeResult(True, "ollama", "loaded", "llama3.2:1b", data={"operation": "load"})
        self.repository.record(result, "model_load")

        session = self.Session()
        try:
            event = session.query(RuntimeEvent).one()
            self.assertEqual(event.event_type, "model_load")
            self.assertTrue(event.success)
            self.assertEqual(event.model_id, "llama3.2:1b")
        finally:
            session.close()


class OllamaRuntimeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_endpoint_gets_ollama_default_port(self):
        adapter = OllamaRuntimeAdapter(
            base_url="http://localhost",
            config_loader=lambda: {"providers_config": {"ollama": {"base_url": "http://localhost"}}},
        )
        self.assertEqual(adapter.base_url, "http://127.0.0.1:11434")
        self.assertFalse(adapter._trust_env)

    async def test_model_inventory_distinguishes_installed_and_loaded(self):
        adapter = OllamaRuntimeAdapter()
        async def fake_request(method, path, **kwargs):
            if path == "/api/tags":
                return {"models": [{"name": "llama3.2:1b", "size": 123}]}
            if path == "/api/ps":
                return {"models": [{"name": "llama3.2:1b"}]}
            raise AssertionError(path)
        adapter._request = fake_request

        result = await adapter.list_models()

        self.assertTrue(result.ok)
        self.assertTrue(result.data["models"][0]["installed"])
        self.assertTrue(result.data["models"][0]["loaded"])

    async def test_shutdown_delegates_only_to_owned_process_controller(self):
        class Controller:
            async def shutdown_owned_process(self):
                return {"status": "stopped", "process_stopped": True}

        adapter = OllamaRuntimeAdapter(controller=Controller())
        result = await adapter.shutdown_owned_process()

        self.assertTrue(result.ok)
        self.assertEqual(result.state, "stopped")
        self.assertTrue(result.data["process_stopped"])

    async def test_unload_sends_explicit_zero_keep_alive(self):
        adapter = OllamaRuntimeAdapter()
        requests = []
        async def fake_request(method, path, **kwargs):
            requests.append((method, path, kwargs.get("json")))
            if path == "/api/tags":
                return {"models": [{"name": "llama3.2:1b"}]}
            if path == "/api/ps":
                return {"models": [{"name": "llama3.2:1b"}]} if len(requests) < 3 else {"models": []}
            if path == "/api/generate":
                return {}
            raise AssertionError(path)
        adapter._request = fake_request

        result = await adapter.unload_model("llama3.2:1b")

        self.assertTrue(result.ok)
        self.assertEqual(requests[2][2]["keep_alive"], 0)


if __name__ == "__main__":
    unittest.main()

