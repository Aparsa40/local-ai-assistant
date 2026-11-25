import asyncio


from core.conversation_agent.contracts import DestinationClass, ExecutionBudget, ExecutionStatus
from core.conversation_agent.strategies.base import ExecutionRequest, ExecutionAborted
from core.conversation_agent.strategies.online import OnlineStrategy
from core.conversation_agent.strategies.offline import OfflineStrategy
from core.interface_manager import InterfaceManagerError


class FakeInterfaceManager:
    def __init__(self, chunks=("hello ", "world"), fail=False):
        self.chunks = list(chunks)
        self.fail = fail
        self.received = []

    async def stream_chat(self, provider_id, messages, model=None, temperature=None):
        self.received.append({"provider_id": provider_id, "messages": [dict(m) for m in messages], "model": model})
        if self.fail:
            raise InterfaceManagerError("inference_failed", "The provider inference request failed.", provider_id)
        for chunk in self.chunks:
            yield chunk


def _request(**overrides):
    data = {
        "request_id": "req_" + "a" * 24,
        "messages": ({"role": "user", "content": "hi"},),
        "provider_id": "openrouter",
        "model": "test/model",
        "destination_class": DestinationClass.CLOUD,
    }
    data.update(overrides)
    return ExecutionRequest(**data)


def test_test_online_strategy_completes():
    asyncio.run(_inner_test_online_strategy_completes())


async def _inner_test_online_strategy_completes():
    im = FakeInterfaceManager()
    result = await OnlineStrategy(im).execute(_request())
    assert result.status is ExecutionStatus.COMPLETED
    assert result.content == "hello world"
    assert im.received[0]["messages"][0]["content"] == "hi"



def test_test_online_strategy_never_leaks_raw_errors():
    asyncio.run(_inner_test_online_strategy_never_leaks_raw_errors())


async def _inner_test_online_strategy_never_leaks_raw_errors():
    im = FakeInterfaceManager(fail=True)
    result = await OnlineStrategy(im).execute(_request())
    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "inference_failed"
    assert "boom" not in result.content



def test_test_offline_unready_fails_closed_without_inference():
    asyncio.run(_inner_test_offline_unready_fails_closed_without_inference())


async def _inner_test_offline_unready_fails_closed_without_inference():
    im = FakeInterfaceManager()
    result = await OfflineStrategy(im, readiness_probe=lambda p, m: False).execute(
        _request(provider_id="ollama", model="local", destination_class=DestinationClass.LOCAL)
    )
    assert result.status is ExecutionStatus.UNAVAILABLE
    assert result.error_code == "local_runtime_not_ready"
    assert im.received == []



def test_test_offline_ready_completes():
    asyncio.run(_inner_test_offline_ready_completes())


async def _inner_test_offline_ready_completes():
    im = FakeInterfaceManager()
    result = await OfflineStrategy(im, readiness_probe=lambda p, m: True).execute(
        _request(provider_id="ollama", model="local", destination_class=DestinationClass.LOCAL)
    )
    assert result.status is ExecutionStatus.COMPLETED



def test_test_output_budget_truncates():
    asyncio.run(_inner_test_output_budget_truncates())


async def _inner_test_output_budget_truncates():
    im = FakeInterfaceManager(chunks=["x" * 600])
    result = await OnlineStrategy(im).execute(_request(budget=ExecutionBudget(max_output_chars=500)))
    assert "[output truncated at the execution budget]" in result.content



def test_test_cancellation_between_chunks():
    asyncio.run(_inner_test_cancellation_between_chunks())


async def _inner_test_cancellation_between_chunks():
    im = FakeInterfaceManager()
    flag = {"cancel": False}

    payload = _request(budget=ExecutionBudget(max_output_chars=500))
    # Simulate the abort flag being raised after the first chunk.
    try:
        async for chunk in im.stream_chat(payload.provider_id, list(payload.messages), model=payload.model):
            flag["cancel"] = True
            if flag["cancel"]:
                raise ExecutionAborted()
    except ExecutionAborted:
        pass
    result = await OnlineStrategy(im).execute(payload, abort_check=lambda: flag["cancel"])
    assert result.status is ExecutionStatus.CANCELLED
    assert result.error_code == "cancelled"



def test_test_abort_check_true_before_execution_cancels():
    asyncio.run(_inner_test_abort_check_true_before_execution_cancels())


async def _inner_test_abort_check_true_before_execution_cancels():
    im = FakeInterfaceManager()
    result = await OnlineStrategy(im).execute(_request(), abort_check=lambda: True)
    assert result.status is ExecutionStatus.CANCELLED
    assert im.received == []

