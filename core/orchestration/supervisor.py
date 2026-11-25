"""The Supervisor agent and the trusted orchestration service (WP-7.4/7.5/7.6).

The Supervisor is a specialized, registered agent hosted by the Phase 6 Agent
Runtime. Its definition is trusted application code; its conversation behavior
is deterministic and performs no model calls and no tool calls. The orchestration
service composition root wires the planning service, assignment resolver,
handoff manager, aggregator, and scheduler; every child task and run is created
and executed exclusively through AgentLifecycleManager and ExecutionController.

The Supervisor never issues grants or approvals and never reaches the
PermissionManager, the ToolRuntime, or a provider directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.agents.contracts import (
    AgentBudgets,
    AgentDefinition,
    CompletionCriteria,
)
from core.orchestration.assignment import CapabilityAssignmentResolver
from core.orchestration.aggregator import ResultAggregator
from core.orchestration.contracts import (
    Goal,
    OrchestrationError,
    PlanStatus,
    new_goal_id,
)
from core.orchestration.handoffs import HandoffManager
from core.orchestration.planner import PlanningService, build_template_plan
from core.orchestration.scheduler import OrchestrationScheduler, OrchestrationSchedulerError
from core.orchestration.graph import validate_plan

SUPERVISOR_AGENT_ID = "supervisor"
SUPERVISOR_AGENT_VERSION = "1.0.0"


class OrchestrationServiceError(OrchestrationError, ValueError):
    """The orchestration service rejected a bounded request."""


class SupervisorAgent:
    """Deterministic supervisor behavior: review the accepted plan, report truthfully.

    The behavior receives only the permission-checked RunContext; plan
    acceptance and validation already happened in trusted application code
    before the run started (WP-7.4 policy checks), and the payload records the
    accepted plan reference without carrying any grant or approval authority.
    """

    @staticmethod
    def definition() -> AgentDefinition:
        return AgentDefinition(
            agent_id=SUPERVISOR_AGENT_ID,
            version=SUPERVISOR_AGENT_VERSION,
            goal=(
                "Review the accepted orchestration plan for the referenced goal "
                "and report its bounds truthfully; coordinate bounded child agents."
            ),
            description=(
                "A bounded, deterministic supervisor. It reviews one accepted "
                "plan produced by the trusted planning service and reports the "
                "plan's task graph bounds. It issues no tool calls, no model "
                "calls, and no grants."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "minLength": 32, "maxLength": 32},
                    "plan_id": {"type": "string", "minLength": 32, "maxLength": 32},
                    "node_count": {"type": "integer", "minimum": 1, "maximum": 32},
                    "planning_strategy": {
                        "type": "string",
                        "enum": ["deterministic_template", "validated_model_proposal"],
                    },
                },
                "required": ["goal_id", "plan_id", "node_count", "planning_strategy"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "maxLength": 500},
                    "plan_id": {"type": "string", "minLength": 32, "maxLength": 32},
                    "node_count": {"type": "integer", "minimum": 0, "maximum": 32},
                    "status": {"type": "string", "enum": ["complete", "incomplete"]},
                    "result": {"type": "object"},
                },
                "required": ["summary", "plan_id", "node_count", "status"],
            },
            completion=CompletionCriteria(
                kind="structured_result_present",
                description="The supervisor reported the accepted plan bounds.",
            ),
            # Deliberately zero-cost: no model tokens, no tool calls.
            budgets=AgentBudgets(
                max_iterations=2,
                deadline_seconds=60,
                max_tool_calls=0,
                max_model_tokens=0,
            ),
            allowed_tools=(),
            allowed_models=(),
            data_scopes=(),
            approval_policy="explicit",
        )

    def decide(self, ctx, state) -> dict:
        payload = ctx.payload if isinstance(ctx.payload, dict) else {}
        plan_id = payload.get("plan_id")
        goal_id = payload.get("goal_id")
        node_count = payload.get("node_count")
        strategy = payload.get("planning_strategy")
        valid = (
            isinstance(plan_id, str) and len(plan_id) == 32
            and isinstance(goal_id, str) and len(goal_id) == 32
            and isinstance(node_count, int) and not isinstance(node_count, bool)
            and 1 <= node_count <= 32
            and strategy in {"deterministic_template", "validated_model_proposal"}
        )
        if not valid:
            return {
                "kind": "finish",
                "status": "incomplete",
                "outcome": {
                    "summary": "No accepted plan reference was bound to this supervisor run.",
                    "plan_id": "0" * 32,
                    "node_count": 0,
                    "status": "incomplete",
                },
            }
        return {
            "kind": "finish",
            "status": "complete",
            "outcome": {
                "summary": (
                    "Accepted plan " + str(plan_id) + " with " + str(node_count)
                    + " bounded nodes (" + str(strategy) + "); coordination continues "
                    "through the trusted orchestration service."
                ),
                "plan_id": plan_id,
                "node_count": node_count,
                "status": "complete",
                "result": {"plan_id": plan_id, "node_count": node_count},
            },
        }


class OrchestrationService:
    """Trusted composition root for supervisor planning and scheduling."""

    def __init__(self, agent_services, *, container, db) -> None:
        from core.repositories.orchestration_repository import (
            OrchestrationAssignmentRepository,
            OrchestrationEventRepository,
            OrchestrationGoalRepository,
            OrchestrationHandoffRepository,
            OrchestrationNodeRepository,
            OrchestrationPlanRepository,
        )

        self._agent_services = agent_services
        self._container = container
        self.db = db
        self.goals = OrchestrationGoalRepository(db)
        self.plans = OrchestrationPlanRepository(db)
        self.nodes = OrchestrationNodeRepository(db)
        self.assignments = OrchestrationAssignmentRepository(db)
        self.handoff_repository = OrchestrationHandoffRepository(db)
        self.events = OrchestrationEventRepository(db)
        self.planner = PlanningService(events=self.events)
        # Least-privilege inputs only: the trusted ToolRegistry and the
        # InterfaceManager evidence source; never sessions or handlers.
        self.resolver = CapabilityAssignmentResolver(
            container.tool_registry,
            interface_manager=container.interface_manager,
            goals=self.goals,
        )
        self.handoff_manager = HandoffManager(self.handoff_repository)
        self.aggregator = ResultAggregator(self.handoff_repository, events=self.events)
        self.scheduler = OrchestrationScheduler(
            self._agent_services.lifecycle,
            self._agent_services.controller,
            plans=self.plans,
            nodes=self.nodes,
            goals=self.goals,
            assignments=self.assignments,
            events=self.events,
            resolver=self.resolver,
            handoff_manager=self.handoff_manager,
            aggregator=self.aggregator,
        )

    # -- goals ------------------------------------------------------------------

    def create_goal(self, *, owner_id: str, description: str, success_criteria: str,
                    data_scopes=(), tool_scopes=(), budgets=None) -> Goal:
        from core.orchestration.contracts import OrchestrationBudgets
        from core.repositories.orchestration_repository import _now, _scopes_to_json, _budgets_to_json
        from core.orchestration.models import OrchestrationGoalRecord

        goal = Goal(
            goal_id=new_goal_id(),
            owner_id=owner_id,
            description=description,
            success_criteria=success_criteria,
            data_scopes=tuple(data_scopes),
            tool_scopes=tuple(tool_scopes),
            budgets=budgets or OrchestrationBudgets(),
        )
        self.db.add(OrchestrationGoalRecord(
            goal_id=goal.goal_id,
            owner_id=goal.owner_id,
            description=goal.description,
            success_criteria=goal.success_criteria,
            data_scopes=_scopes_to_json(goal.data_scopes),
            tool_scopes=list(goal.tool_scopes),
            budgets=_budgets_to_json(goal.budgets),
            status="open",
            created_at=goal.created_at.replace(tzinfo=None),
        ))
        self.db.commit()
        return goal

    def get_goal(self, goal_id: str) -> Goal | None:
        from core.orchestration.contracts import OrchestrationBudgets
        from core.repositories.orchestration_repository import (
            _scopes_from_json, _budgets_from_json,
        )

        record = self.db.query(self._goal_model()).filter(
            self._goal_model().goal_id == goal_id
        ).first()
        if record is None:
            return None
        return Goal(
            goal_id=record.goal_id,
            owner_id=record.owner_id,
            description=record.description,
            success_criteria=record.success_criteria,
            data_scopes=_scopes_from_json(record.data_scopes, record.owner_id),
            tool_scopes=tuple(record.tool_scopes or ()),
            budgets=_budgets_from_json(record.budgets),
            created_at=record.created_at.replace(tzinfo=timezone.utc)
            if record.created_at.tzinfo is None else record.created_at,
        )

    @staticmethod
    def _goal_model():
        from core.orchestration.models import OrchestrationGoalRecord

        return OrchestrationGoalRecord

    # -- planning ------------------------------------------------------------------

    async def plan_goal(self, goal_id: str, *, owner_id: str, strategy: str = "deterministic_template",
                        proposal_text: str | None = None, revision: int = 1) -> dict:
        """Plan one goal beneath a hosted supervisor run, then persist and accept it.

        The supervisor task/run is created through the trusted lifecycle before
        planning so the plan always references a real parent run; the parent run
        itself stays PENDING until the plan documents its bounds.
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            raise OrchestrationServiceError("The goal was not found.")
        if goal.owner_id != owner_id:
            raise OrchestrationServiceError("The goal owner does not match the requester.")
        task = self._agent_services.lifecycle.create_task(
            agent_id=SUPERVISOR_AGENT_ID,
            agent_version=SUPERVISOR_AGENT_VERSION,
            owner_id=owner_id,
            title=("Supervise goal " + goal_id)[:200],
            payload={"goal_id": goal.goal_id, "planning_strategy": strategy},
            data_scopes=(),
        )
        run = self._agent_services.lifecycle.create_run(task.task_id)
        if strategy == "deterministic_template":
            plan = self.planner.build_plan(
                goal, parent_run_id=run.run_id, parent_task_id=task.task_id,
            )
        elif strategy == "validated_model_proposal":
            if proposal_text is None:
                raise OrchestrationServiceError(
                    "The validated_model_proposal strategy requires a proposal or a model route."
                )
            plan = self.planner.build_plan_from_proposal(
                goal, proposal_text,
                parent_run_id=run.run_id, parent_task_id=task.task_id, revision=revision,
            )
        else:
            raise OrchestrationServiceError("Unsupported planning strategy.")
        self.events.record(
            plan_id=plan.plan_id, node_id=None,
            event_type="plan_created", outcome=plan.status.value,
            metadata={"strategy": strategy, "parent_run_id": run.run_id},
        )
        persisted = self.plans.create(plan)
        # Application-side policy gate: accept only after full revalidation.
        from core.orchestration.graph import validate_plan as _validate

        _validate(persisted, goal=goal)
        accepted = self.scheduler.accept_plan(persisted.plan_id)
        payload = {
            "goal_id": goal.goal_id,
            "plan_id": plan.plan_id,
            "node_count": len(plan.nodes),
            "planning_strategy": strategy,
        }
        updated_task = self._agent_services.tasks.update_payload(task.task_id, payload)
        # The supervisor run documents the accepted plan; it never carries
        # further authority and completes deterministically.
        final_run = await self._agent_services.controller.execute(run.run_id)
        self.events.record(
            plan_id=plan.plan_id, node_id=None,
            event_type="supervisor_run_completed", outcome=final_run.status.value,
            metadata={"run_id": final_run.run_id},
        )
        return {
            "goal_id": goal.goal_id,
            "plan_id": persisted.plan_id,
            "status": accepted.status.value,
            "supervisor_run_id": final_run.run_id,
            "node_count": len(persisted.nodes),
        }

    async def execute_plan(self, plan_id: str) -> object:
        return await self.scheduler.run_plan(plan_id)

    async def cancel_plan(self, plan_id: str, *, reason: str = "requested_by_owner") -> object:
        return await self.scheduler.cancel_plan(plan_id, reason=reason)

    def reconcile(self, plan_id: str) -> object:
        return self.scheduler.reconcile_plan(plan_id)

    def plan_view(self, plan_id: str) -> dict | None:
        """Read-only serialization of one plan for the API surface."""
        plan = self.plans.get(plan_id)
        if plan is None:
            return None
        return {
            "plan_id": plan.plan_id,
            "goal_id": plan.goal_id,
            "parent_run_id": plan.parent_run_id,
            "owner_id": plan.owner_id,
            "revision": plan.revision,
            "status": plan.status.value,
            "error_code": plan.error_code,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "ordinal": node.ordinal,
                    "title": node.title,
                    "status": node.status.value,
                    "agent_id": node.agent_id,
                    "agent_version": node.agent_version,
                    "run_id": node.run_id,
                    "attempts": node.attempts,
                    "max_retries": node.max_retries,
                    "error_code": node.error_code,
                }
                for node in sorted(plan.nodes, key=lambda item: (item.ordinal, item.node_id))
            ],
            "dependencies": [
                {
                    "dependency_id": dependency.dependency_id,
                    "node_id": dependency.node_id,
                    "depends_on": dependency.depends_on,
                    "policy": dependency.policy,
                    "status": dependency.status.value,
                }
                for dependency in plan.dependencies
            ],
            "assignments": list(self.assignments.list_for_plan(plan.plan_id, limit=100)),
            "handoffs": [
                {
                    "handoff_id": handoff.handoff_id,
                    "node_id": handoff.node_id,
                    "from_run_id": handoff.from_run_id,
                    "status": handoff.status,
                    "summary": str(handoff.payload.get("summary", ""))[:500],
                }
                for handoff in self.handoff_manager.list_for_plan(plan.plan_id, limit=100)
            ],
            "events": list(self.events.list_for_plan(plan.plan_id, limit=100)),
        }
