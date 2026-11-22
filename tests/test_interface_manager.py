import unittest

from core.interface_manager import InterfaceManager, InterfaceManagerError


class FakeProvider:
    def __init__(self, config):
        self.config = config

    async def list_models(self):
        return ["local-test-model"]

    async def chat_stream(self, messages, model, temperature=0.7):
        yield f"{model}:"
        yield messages[-1]["content"]


class InterfaceManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = InterfaceManager(
            config_loader=lambda: {
                "providers_config": {"local_test": {"base_url": "http://localhost"}}
            },
            provider_factories={"local_test": FakeProvider},
            capabilities_getter=lambda provider_id: {"streaming": True},
            timeout_seconds=1,
        )

    def test_lists_registered_providers_without_secrets(self):
        providers = self.manager.list_providers()
        self.assertEqual(providers[0]["id"], "local_test")
        self.assertTrue(providers[0]["capabilities_available"])
        self.assertNotIn("api_key", providers[0])

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(InterfaceManagerError) as context:
            self.manager.get_capabilities("missing")
        self.assertEqual(context.exception.category, "unknown_provider")

    async def test_lists_exact_model_ids(self):
        self.assertEqual(
            await self.manager.list_models("local_test"),
            ["local-test-model"],
        )

    async def test_connection_probe_reports_catalog_reachability(self):
        result = await self.manager.check_connection("local_test")
        self.assertEqual(result["status"], "reachable")
        self.assertEqual(result["probe"], "model_catalog")
        self.assertEqual(result["model_count"], 1)

    async def test_streams_chat_through_provider_boundary(self):
        chunks = [
            chunk async for chunk in self.manager.stream_chat(
                "local_test",
                [{"role": "user", "content": "hello"}],
                "local-test-model",
            )
        ]
        self.assertEqual(chunks, ["local-test-model:", "hello"])

    def test_operator_catalog_exposes_provider_level_discovery_and_quota_policy(self):
        manager = InterfaceManager()
        catalog = manager.get_provider_catalog("openrouter")

        self.assertEqual(catalog["operator"]["catalog_mode"], "live_catalog_and_router_alias")
        self.assertIn("openrouter/free", catalog["operator"]["router_aliases"])
        self.assertTrue(catalog["operator"]["quota"]["live_remaining"])
        self.assertEqual(catalog["catalog_source"], "local_operator_manifest")

    def test_operator_catalog_does_not_invoke_model_discovery(self):
        manager = InterfaceManager(
            provider_factories={"groq": FakeProvider},
            capabilities_getter=lambda _provider_id: {"models": {"openai/gpt-oss-20b": {"tasks": ["analysis"]}}},
        )
        catalog = manager.get_provider_catalog("groq")
        self.assertEqual(catalog["operator"]["catalog_mode"], "live_authenticated_catalog")
        self.assertEqual(catalog["model_metadata_evidence"], "curated_manifest")
    async def test_quota_status_uses_provider_telemetry_when_available(self):
        class FakeQuotaProvider(FakeProvider):
            async def get_quota_status(self):
                return {"status": "observed", "data": {"usage": 2.5, "limit_remaining": 7.5}}

        manager = InterfaceManager(
            config_loader=lambda: {"providers_config": {"openrouter": {}}},
            provider_factories={"openrouter": FakeQuotaProvider},
            capabilities_getter=lambda _provider_id: {},
        )
        result = await manager.get_quota_status("openrouter")
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["data"]["limit_remaining"], 7.5)

    async def test_quota_status_does_not_invent_unavailable_balances(self):
        manager = InterfaceManager(
            config_loader=lambda: {"providers_config": {"cohere": {}}},
            provider_factories={"cohere": FakeProvider},
            capabilities_getter=lambda _provider_id: {"quota": {"runtime": {"status": "unknown"}}},
        )
        result = await manager.get_quota_status("cohere")
        self.assertEqual(result["status"], "not_exposed")
        self.assertNotIn("remaining", result)

    async def test_stream_chat_preserves_cohere_adapter_default_temperature(self):
        class CohereDefaultProvider(FakeProvider):
            def __init__(self, config):
                super().__init__(config)
                self.received_temperature = None

            async def chat_stream(self, messages, model, temperature=0.3):
                self.received_temperature = temperature
                yield "ok"

        provider = CohereDefaultProvider({})
        manager = InterfaceManager(
            config_loader=lambda: {"providers_config": {"cohere": {}}},
            provider_factories={"cohere": lambda _config: provider},
            capabilities_getter=lambda _provider_id: {},
        )

        chunks = [
            chunk async for chunk in manager.stream_chat(
                "cohere", [{"role": "user", "content": "hello"}], "command-r"
            )
        ]

        self.assertEqual(chunks, ["ok"])
        self.assertEqual(provider.received_temperature, 0.3)

    async def test_stream_chat_forwards_explicit_temperature_override(self):
        class CohereDefaultProvider(FakeProvider):
            def __init__(self, config):
                super().__init__(config)
                self.received_temperature = None

            async def chat_stream(self, messages, model, temperature=0.3):
                self.received_temperature = temperature
                yield "ok"

        provider = CohereDefaultProvider({})
        manager = InterfaceManager(
            config_loader=lambda: {"providers_config": {"cohere": {}}},
            provider_factories={"cohere": lambda _config: provider},
            capabilities_getter=lambda _provider_id: {},
        )

        chunks = [
            chunk async for chunk in manager.stream_chat(
                "cohere",
                [{"role": "user", "content": "hello"}],
                "command-r",
                temperature=0.9,
            )
        ]

        self.assertEqual(chunks, ["ok"])
        self.assertEqual(provider.received_temperature, 0.9)

if __name__ == "__main__":
    unittest.main()
