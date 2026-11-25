import asyncio
import contextlib
import json
from types import SimpleNamespace

from core.conversation_agent.operations import OperationRegistry
from core.conversation_agent.service import ConversationAgentService


class FakeConversationService:
    def __init__(self):
        self.prepared = []
        self.assistant = []

    def _authorize(self, *args, **kwargs):
        return None

    def prepare_chat(self, session_id, message):
        self.prepared.append((session_id, message))

    def append_assistant_message(self, session_id, content, model):
        self.assistant.append((session_id, content, model))


class FakeContextManager:
    def __init__(self, items):
        self.items = items

    def assemble(self, request):
        return SimpleNamespace(items=tuple(self.items))


def context_item(source_type, ref, content="piece", role="user"):
    return SimpleNamespace(source_type=source_type, source_ref=ref, content=content, role=role)


class LocalNeverReadyIM:
    """Local provider always unusable; cloud provider streams an answer."""

    def __init__(self):
        self.received = []

    async def stream_chat(self, provider_id, messages, model=None, temperature=None):
        self.received.append(provider_id)
        if provider_id == "ollama":
            raise RuntimeError("local model is not running")
        for chunk in ["cloud answer"]:
            yield chunk


async def _probe(provider_id, model):
    return False


def _collect(service, payload):
    async def iterator():
        return [chunk async for chunk in service.stream(None, None, None, payload)]
    return iterator()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_selected_provider_preserved_when_no_failure():
    async def ready(provider_id, model):
        return True

    im = LocalNeverReadyIM()
    conversation = FakeConversationService()
    service = ConversationAgentService(
        interface_manager=im,
        conversation_builder=lambda db, access, pm: conversation,
        context_builder=lambda conv, db: FakeContextManager([context_item("conversation", "message:1")]),
        session_factory=lambda: contextlib.nullcontext(None),
        registry=OperationRegistry(),
        readiness_probe=ready,
    )
    payload = {"session_id": 1, "message": "q", "request_id": "req_" + "b" * 24, "provider_id": "ollama", "model": "local-model"}
    parsed = [json.loads(c[len("data: "):]) for c in run(_collect(service, payload))]
    final = parsed[-1]
    assert final["data"]["status"] == "completed"
    assert final["data"]["provenance"]["fallback_applied"] is False


def test_local_unready_falls_back_to_authorized_cloud_and_discloses():
    im = LocalNeverReadyIM()
    conversation = FakeConversationService()
    service = ConversationAgentService(
        interface_manager=im,
        conversation_builder=lambda db, access, pm: conversation,
        context_builder=lambda conv, db: FakeContextManager([context_item("conversation", "message:1")]),
        session_factory=lambda: contextlib.nullcontext(None),
        registry=OperationRegistry(),
        readiness_probe=_probe,
        fallback_order=("openrouter",),
    )
    payload = {"session_id": 1, "message": "q", "request_id": "req_" + "c" * 24, "provider_id": "ollama", "model": "local-model"}
    parsed = [json.loads(c[len("data: "):]) for c in run(_collect(service, payload))]
    final = parsed[-1]
    assert im.received[0] == "ollama"
    assert "openrouter" in im.received
    assert final["data"]["status"] == "partial"
    assert final["data"]["provenance"]["fallback_applied"] is True
    assert "cloud answer" in final["data"]["content"]
    assert final["data"]["provenance"]["fallback_reason"]


def test_local_unready_fallback_denied_for_private_context():
    im = LocalNeverReadyIM()
    conversation = FakeConversationService()
    service = ConversationAgentService(
        interface_manager=im,
        conversation_builder=lambda db, access, pm: conversation,
        context_builder=lambda conv, db: FakeContextManager([context_item("memory", "memory:1", "PRIVATE-MEMORY")]),
        session_factory=lambda: contextlib.nullcontext(None),
        registry=OperationRegistry(),
        readiness_probe=_probe,
        fallback_order=("openrouter",),
    )
    payload = {
        "session_id": 1, "message": "q", "request_id": "req_" + "d" * 24,
        "provider_id": "ollama", "model": "local-model",
        "memory_scopes": [{"domain": "memory", "scope_type": "user", "scope_id": "1", "owner_id": "local-user"}],
    }
    parsed = [json.loads(c[len("data: "):]) for c in run(_collect(service, payload))]
    final = parsed[-1]
    # Private context must never reach the cloud fallback; no transmission happened.
    assert "openrouter" not in im.received
    assert final["data"]["status"] in {"partial", "unavailable"}
    assert "cloud answer" not in final["data"]["content"]
