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


class _ApprovalAwareOrchestrationService:
    def __init__(self):
        self.run_status = "paused"
        self.pending_approval_id = "approval-123"
        self.resumed = []

    def create_goal(self, **kwargs):
        self.owner_id = kwargs["owner_id"]
        return SimpleNamespace(goal_id="goal-" + "a" * 24)

    async def plan_goal(self, goal_id, owner_id):
        assert owner_id == self.owner_id
        return {"plan_id": "plan-" + "b" * 24}

    async def execute_plan(self, plan_id):
        raise RuntimeError("scheduler stopped at approval-required child run")

    def plan_view(self, plan_id):
        return {
            "status": "completed" if self.run_status == "succeeded" else "cancelled" if self.run_status == "cancelled" else "running",
            "nodes": [{
                "node_id": "node-1",
                "title": "Approval-gated task",
                "status": "completed" if self.run_status == "succeeded" else "cancelled" if self.run_status == "cancelled" else "running",
                "run_id": "run-123",
                "run_status": self.run_status,
                "pending_approval_id": self.pending_approval_id,
            }],
            "handoffs": [{
                "summary": "Completed after explicit approval.",
            }] if self.run_status == "succeeded" else [],
        }

    async def resume_plan(self, plan_id, *, run_id, owner_id):
        assert plan_id == "plan-" + "b" * 24
        assert run_id == "run-123"
        assert owner_id == self.owner_id
        self.resumed.append(run_id)
        self.run_status = "succeeded"
        self.pending_approval_id = None

    async def cancel_plan(self, plan_id, *, reason):
        assert plan_id == "plan-" + "b" * 24
        assert reason == "approval_timeout"
        self.run_status = "cancelled"
        self.pending_approval_id = None


def test_delegation_emits_approval_callback_and_resumes_same_child_run():
    orchestration = _ApprovalAwareOrchestrationService()
    gateway = OrchestrationGateway(
        orchestration_factory=lambda db: orchestration,
        session_factory=lambda: nullcontext(None),
    )
    request = ConversationRequest.from_payload(
        {"session_id": 1, "message": "delegate an approval-gated task", "request_id": "req_" + "a" * 24},
        session_id=1,
    )
    approval_events = []

    async def on_approval(payload):
        approval_events.append(payload)
        # Simulate the authorized UI flow completing the same child run.
        orchestration.run_status = "succeeded"
        orchestration.pending_approval_id = None

    outcome = asyncio.run(gateway.delegate(
        request,
        authorized_scopes=(),
        owner_id="trusted-owner",
        approval_callback=on_approval,
    ))

    assert len(approval_events) == 1
    assert approval_events[0] == {
        "approval_id": "approval-123",
        "run_id": "run-123",
        "node_id": "node-1",
        "plan_id": "plan-" + "b" * 24,
    }
    assert orchestration.resumed == ["run-123"]
    assert outcome.status is ExecutionStatus.COMPLETED
    assert outcome.content == "Completed after explicit approval."


def test_approval_timeout_cancels_the_paused_plan():
    orchestration = _ApprovalAwareOrchestrationService()
    gateway = OrchestrationGateway(
        orchestration_factory=lambda db: orchestration,
        session_factory=lambda: nullcontext(None),
    )
    request = ConversationRequest.from_payload(
        {
            "session_id": 1,
            "message": "delegate with a short approval budget",
            "request_id": "req_" + "b" * 24,
            "budget": {"wall_clock_seconds": 1},
        },
        session_id=1,
    )

    async def on_approval(payload):
        assert payload["approval_id"] == "approval-123"

    outcome = asyncio.run(gateway.delegate(
        request,
        authorized_scopes=(),
        owner_id="trusted-owner",
        approval_callback=on_approval,
    ))

    assert orchestration.run_status == "cancelled"
    assert outcome.status is ExecutionStatus.CANCELLED
