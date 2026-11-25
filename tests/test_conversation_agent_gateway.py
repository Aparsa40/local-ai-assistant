"""Cancellation propagation tests for Phase 8 Supervisor delegation."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

from core.conversation_agent.contracts import ConversationRequest, ExecutionStatus
from core.conversation_agent.orchestration_gateway import OrchestrationGateway


class _CancellableOrchestrationService:
    def __init__(self):
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.cancelled = False

    def create_goal(self, **kwargs):
        return SimpleNamespace(goal_id="goal-" + "g" * 24)

    async def plan_goal(self, goal_id, owner_id):
        return {"plan_id": "plan-" + "p" * 24}

    async def execute_plan(self, plan_id):
        self.started.set()
        await self.finished.wait()

    async def cancel_plan(self, plan_id, reason):
        self.cancelled = True
        self.finished.set()

    def plan_view(self, plan_id):
        return {
            "status": "cancelled" if self.cancelled else "running",
            "nodes": [{"node_id": "n1", "title": "task", "status": "cancelled"}],
            "handoffs": [],
        }


def test_turn_cancellation_propagates_to_phase7_plan():
    orchestration = _CancellableOrchestrationService()
    gateway = OrchestrationGateway(
        orchestration_factory=lambda db: orchestration,
        session_factory=lambda: nullcontext(None),
    )
    request = ConversationRequest.from_payload(
        {"session_id": 1, "message": "delegate this bounded task", "request_id": "req_" + "c" * 24},
        session_id=1,
    )
    cancellation = {"requested": False}

    async def scenario():
        task = asyncio.create_task(
            gateway.delegate(
                request,
                authorized_scopes=(),
                cancel_check=lambda: cancellation["requested"],
            )
        )
        await orchestration.started.wait()
        cancellation["requested"] = True
        return await task

    outcome = asyncio.run(scenario())
    assert orchestration.cancelled is True
    assert outcome.status is ExecutionStatus.CANCELLED
