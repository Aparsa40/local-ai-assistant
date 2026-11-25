"""Bounded delegation into the existing Phase 7 OrchestrationService (WP-8.4).

The gateway calls the trusted composition root directly; it never issues HTTP
requests back into the application's own API, never widens scopes, and never
claims success for incomplete orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass

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

    def __init__(self, orchestration_factory, session_factory, *, default_budgets=None) -> None:
        self._orchestration_factory = orchestration_factory
        self._session_factory = session_factory
        self._default_budgets = default_budgets

    async def delegate(
        self,
        request: ConversationRequest,
        *,
        authorized_scopes: tuple[DataScopeRef, ...],
    ) -> DelegatedOutcome:
        from core.agents.contracts import DataScope
        from core.orchestration.contracts import OrchestrationBudgets
        from core.orchestration.supervisor import OrchestrationServiceError

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
                    owner_id="local-user",
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
                planned = await service.plan_goal(goal.goal_id, owner_id="local-user")
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
                await service.execute_plan(plan_id)
            except Exception:
                view = service.plan_view(plan_id) or {}
                return DelegatedOutcome(
                    status=ExecutionStatus.FAILED,
                    content="",
                    goal_id=goal.goal_id,
                    plan_id=plan_id,
                    node_outcomes=tuple(view.get("nodes", [])),
                    limitations=("Plan execution failed before reaching a terminal aggregate.",),
                    error_code="execution_failed",
                )
            view = service.plan_view(plan_id) or {}
            return self._map_view(view, goal.goal_id, plan_id)

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
