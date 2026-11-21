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


if __name__ == "__main__":
    unittest.main()
