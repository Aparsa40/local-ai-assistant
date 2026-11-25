"""Bounded delegation into the existing Phase 7 OrchestrationService (WP-8.4).

The gateway calls the trusted composition root directly; it never issues HTTP
requests back into the application's own API, never widens scopes, and never
claims success for incomplete orchestration.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from core.conversation_agent.contracts import (
    ConversationRequest,
    DataScopeRef,
    ExecutionStatus,
)


@dataclass(frozen=True)
class DelegatedOutcome:
    status: ExecutionStatus
    content: str
    goal_id: str | None = None
    plan_id: str | None = None
    node_outcomes: tuple[dict, ...] = ()
    limitations: tuple[str, ...] = ()
    error_code: str | None = None


class OrchestrationGateway:
    """Submit one bounded goal and map persisted results to a truthful outcome."""

    def __init__(
        self,
        orchestration_factory,
        session_factory,
        *,
        default_budgets=None,
        approval_wait_seconds: float | None = None,
    ) -> None:
        self._orchestration_factory = orchestration_factory
        self._session_factory = session_factory
        self._default_budgets = default_budgets
        self._approval_wait_seconds = approval_wait_seconds

    async def delegate(
        self,
        request: ConversationRequest,
        *,
        authorized_scopes: tuple[DataScopeRef, ...],
        cancel_check: Callable[[], bool] | None = None,
        approval_callback: Callable[[dict], Awaitable[None]] | None = None,
        owner_id: str = "local-user",
    ) -> DelegatedOutcome:
        from core.agents.contracts import DataScope
        from core.orchestration.contracts import OrchestrationBudgets
        from core.orchestration.supervisor import OrchestrationServiceError

        started_at = asyncio.get_running_loop().time()
        # Child scopes must be a subset of the authorized parent scope.
        allowed = {(scope.domain, scope.scope_type, scope.scope_id, scope.owner_id) for scope in authorized_scopes}
        child_scopes: tuple[DataScope, ...] = tuple(
            DataScope(
                domain=scope.domain, scope_type=scope.scope_type,
                scope_id=scope.scope_id, owner_id=scope.owner_id,
            )
            for scope in request.memory_scopes + request.knowledge_scopes
            if (scope.domain, scope.scope_type, scope.scope_id, scope.owner_id) in allowed
        )
        with self._session_factory() as db:
            service = self._orchestration_factory(db)
            try:
                goal = service.create_goal(
                    owner_id=owner_id,
                    description=request.message[:2000],
                    success_criteria=request.message[:500],
                    data_scopes=child_scopes,
                    tool_scopes=(),
                    budgets=self._default_budgets,
                )
            except (TypeError, ValueError, OrchestrationServiceError):
                return DelegatedOutcome(
                    status=ExecutionStatus.BLOCKED,
                    content="",
                    limitations=("The delegation goal was rejected as out of bounds.",),
                    error_code="goal_rejected",
                )
            try:
                planned = await service.plan_goal(goal.goal_id, owner_id=owner_id)
            except Exception:
                return DelegatedOutcome(
                    status=ExecutionStatus.UNAVAILABLE,
                    content="",
                    goal_id=goal.goal_id,
                    limitations=("The orchestration service could not plan the requested goal.",),
                    error_code="planning_unavailable",
                )
            plan_id = planned.get("plan_id") if isinstance(planned, dict) else None
            try:
                if cancel_check is not None and cancel_check():
                    await service.cancel_plan(plan_id, reason="conversation_cancelled")
                else:
                    execution = asyncio.create_task(service.execute_plan(plan_id))
                    while not execution.done():
                        if cancel_check is not None and cancel_check():
                            await service.cancel_plan(plan_id, reason="conversation_cancelled")
                            break
                        await asyncio.sleep(0.05)
                    await execution
            except Exception:
                self._refresh_session(db)
                view = service.plan_view(plan_id) or {}
                pending = self._pending_approval(view)
                if pending is None or approval_callback is None:
                    return DelegatedOutcome(
                        status=ExecutionStatus.FAILED,
                        content="",
                        goal_id=goal.goal_id,
                        plan_id=plan_id,
                        node_outcomes=tuple(view.get("nodes", [])),
                        limitations=("Plan execution failed before reaching a terminal aggregate.",),
                        error_code="execution_failed",
                    )
                view = await self._continue_approval_chain(
                    service,
                    db,
                    view,
                    plan_id=plan_id,
                    owner_id=owner_id,
                    cancel_check=cancel_check,
                    approval_callback=approval_callback,
                    timeout_seconds=(
                        self._approval_wait_seconds
                        if self._approval_wait_seconds is not None
                        else request.budget.wall_clock_seconds - (
                            asyncio.get_running_loop().time() - started_at
                        ) - 1.0
                    ),
                )
                if view is None:
                    view = service.plan_view(plan_id) or {}
                    return DelegatedOutcome(
                        status=ExecutionStatus.UNAVAILABLE,
                        content="",
                        goal_id=goal.goal_id,
                        plan_id=plan_id,
                        node_outcomes=tuple(view.get("nodes", [])),
                        limitations=("Approval was not completed within the conversation execution budget.",),
                        error_code="approval_timeout",
                    )
            self._refresh_session(db)
            view = service.plan_view(plan_id) or {}
            return self._map_view(view, goal.goal_id, plan_id)

    @staticmethod
    def _refresh_session(db) -> None:
        """Release stale read state while a human approval is handled elsewhere."""
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.expire_all()
        except Exception:
            pass

    @staticmethod
    def _pending_approval(view: dict) -> dict | None:
        return next((
            node for node in view.get("nodes", [])
            if node.get("run_status") == "paused" and node.get("pending_approval_id")
        ), None)

    async def _continue_approval_chain(
        self,
        service,
        db,
        view: dict,
        *,
        plan_id: str,
        owner_id: str,
        cancel_check,
        approval_callback,
        timeout_seconds: int,
    ) -> dict | None:
        """Wait for a user decision, execute the same child run, then resume its plan."""
        if timeout_seconds <= 0:
            await service.cancel_plan(plan_id, reason="approval_timeout")
            self._refresh_session(db)
            return service.plan_view(plan_id) or {}
        deadline = asyncio.get_running_loop().time() + float(timeout_seconds)
        pending = self._pending_approval(view)
        while pending is not None:
            await approval_callback({
                "approval_id": pending["pending_approval_id"],
                "run_id": pending["run_id"],
                "node_id": pending["node_id"],
                "plan_id": plan_id,
            })
            while True:
                if cancel_check is not None and cancel_check():
                    await service.cancel_plan(plan_id, reason="conversation_cancelled")
                    self._refresh_session(db)
                    return service.plan_view(plan_id) or {}
                self._refresh_session(db)
                view = service.plan_view(plan_id) or {}
                current = next((
                    node for node in view.get("nodes", [])
                    if node.get("run_id") == pending.get("run_id")
                ), None)
                if current is None:
                    return view
                if current.get("run_status") in {"succeeded", "failed", "cancelled"}:
                    try:
                        await service.resume_plan(
                            plan_id,
                            run_id=str(current["run_id"]),
                            owner_id=owner_id,
                        )
                    except Exception:
                        self._refresh_session(db)
                        view = service.plan_view(plan_id) or {}
                        next_pending = self._pending_approval(view)
                        if next_pending is None:
                            return None
                        pending = next_pending
                        break
                    self._refresh_session(db)
                    view = service.plan_view(plan_id) or {}
                    pending = self._pending_approval(view)
                    if pending is None:
                        return view
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    await service.cancel_plan(plan_id, reason="approval_timeout")
                    self._refresh_session(db)
                    return service.plan_view(plan_id) or {}
                await asyncio.sleep(0.1)
        return view

    @staticmethod
    def _map_view(view: dict, goal_id: str, plan_id: str) -> DelegatedOutcome:
        nodes = tuple(view.get("nodes", []))
        statuses = [str(node.get("status", "pending")) for node in nodes]
        completed = statuses.count("completed")
        failed = statuses.count("failed")
        cancelled = statuses.count("cancelled")
        if plan_status := view.get("status"):
            plan_status = str(plan_status)
        handoff_summaries = [
            str(handoff.get("summary", ""))
            for handoff in view.get("handoffs", [])
            if str(handoff.get("summary", "")).strip()
        ]
        limitations: list[str] = []
        for node in nodes:
            if str(node.get("status")) != "completed":
                limitations.append(
                    "Task '" + str(node.get("title", node.get("node_id", "")))[:80]
                    + "' did not complete (" + str(node.get("status", "unknown")) + ")."
                )
        if failed and completed:
            status = ExecutionStatus.PARTIAL
        elif failed or cancelled and completed == 0:
            status = ExecutionStatus.FAILED if failed else ExecutionStatus.CANCELLED
        elif completed and not limitations:
            status = ExecutionStatus.COMPLETED
        elif completed:
            status = ExecutionStatus.PARTIAL
        else:
            status = ExecutionStatus.UNAVAILABLE
            limitations.append("No delegated task completed.")
        if plan_status in {"cancelled", "paused"}:
            status = ExecutionStatus.CANCELLED if plan_status == "cancelled" else ExecutionStatus.UNAVAILABLE
            limitations.append("The orchestration plan ended in state '" + str(plan_status) + "'.")
        content = "\n\n".join(handoff_summaries)
        return DelegatedOutcome(
            status=status,
            content=content,
            goal_id=goal_id,
            plan_id=plan_id,
            node_outcomes=nodes,
            limitations=tuple(limitations[:20]),
        )
