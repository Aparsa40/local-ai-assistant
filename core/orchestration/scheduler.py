"""Deterministic, sequential orchestration scheduler for accepted plans.

The scheduler is the only component that turns plan nodes into Agent Runtime
tasks and runs. It never executes tools, never calls models, and never issues
grants: every child task/run is created through AgentLifecycleManager and
executed through the existing ExecutionController, so tool calls flow through
ToolRuntime and PermissionManager and model calls through InterfaceManager.

Scheduling is sequential in Phase 7 (max_active_tasks is honored as one
concurrent execution). Scheduling decisions, node transitions, assignment
outcomes, handoffs, and terminal decisions are persisted before the next step
so restart recovery can reconcile without duplicating side effects.

Idempotency: a node is executed at most once per attempt. Only PENDING nodes
with all prerequisites COMPLETED are scheduled; a crash between SCHEDULED and
task creation is reconciled by resume_plan, never silently re-executed.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from core.agents.contracts import AgentRunStatus
from core.agents.lifecycle import AgentLifecycleManager
from core.orchestration.contracts import (
    DependencyStatus,
    NodeStatus,
    PlanStatus,
)
from core.orchestration.graph import build_prerequisites


class OrchestrationSchedulerError(Exception):
    """The scheduler could not make progress on a plan."""


class OrchestrationScheduler:
    """Sequential, restart-safe plan scheduler over the Agent Runtime."""

    def __init__(
        self,
        lifecycle: AgentLifecycleManager,
        controller,
        *,
        plans,
        nodes,
        goals,
        assignments,
        events,
        resolver,
        handoff_manager,
        aggregator,
        clock=None,
        monotonic=None,
    ) -> None:
        self.lifecycle = lifecycle
        self.controller = controller
        self.plans = plans
        self.nodes = nodes
        self.goals = goals
        self.assignments = assignments
        self.events = events
        self.resolver = resolver
        self.handoff_manager = handoff_manager
        self.aggregator = aggregator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic

    # -- prerequisites and eligibility ---------------------------------------

    @staticmethod
    def _dependency_status_map(dependencies) -> dict:
        result: dict = {}
        for dependency in dependencies:
            statuses = result.setdefault(dependency.node_id, [])
            statuses.append((dependency.depends_on, dependency))
        return result

    def _prerequisite_nodes_satisfied(self, plan, node_id: str, node_states: dict) -> bool:
        for prerequisite in build_prerequisites(plan).get(node_id, []):
            state = node_states.get(prerequisite)
            if state is None or state.status is not NodeStatus.COMPLETED:
                return False
        return True

    def _any_prerequisite_terminal_failure(self, plan, node_id: str, node_states: dict) -> bool:
        for prerequisite in build_prerequisites(plan).get(node_id, []):
            state = node_states.get(prerequisite)
            if state is not None and state.status in {
                NodeStatus.FAILED, NodeStatus.CANCELLED, NodeStatus.SKIPPED,
            }:
                return True
        return False

    def _fail_event(self, plan_id: str, node_id, event_type: str, message: str) -> None:
        try:
            self.events.record(
                plan_id=plan_id,
                node_id=node_id,
                event_type=event_type,
                outcome="failed",
                metadata={"reason_code": event_type, "message": message[:200]},
            )
        except Exception:
            # Event loss over a bounded failure is surfaced to the caller by
            # the node state; never mask a failure as a silent stop.
            pass

    # -- plan level operations --------------------------------------------------

    def _mark_plan_status(self, plan_id: str, plan, target: PlanStatus, **updates):
        from core.orchestration.contracts import PlanValidationError

        allowed = {
            PlanStatus.ACCEPTED: {PlanStatus.RUNNING, PlanStatus.CANCELLED},
            PlanStatus.DRAFT: {PlanStatus.ACCEPTED},
            PlanStatus.RUNNING: {
                PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED,
            },
        }
        if target not in allowed.get(plan.status, frozenset()):
            raise OrchestrationSchedulerError(
                "Plan transition " + plan.status.value + " -> " + target.value + " is not allowed."
            )
        updated = self.plans.transition(
            plan_id, expected_version=plan.version, status=target, **updates,
        )
        if updated is None:
            raise OrchestrationSchedulerError("The plan was not found.")
        return updated

    def accept_plan(self, plan_id: str) -> object:
        """Accept a validated draft plan; acceptance precedes any scheduling."""
        plan = self._require(plan_id)
        if plan.status is not PlanStatus.DRAFT:
            raise OrchestrationSchedulerError("Only draft plans can be accepted.")
        return self._mark_plan_status(plan_id, plan, PlanStatus.ACCEPTED)

    def _require(self, plan_id: str):
        plan = self.plans.get(plan_id)
        if plan is None:
            raise OrchestrationSchedulerError("The plan was not found.")
        return plan

    async def run_plan(self, plan_id: str) -> object:
        """Drive one accepted plan to a terminal aggregate; awaits child runs."""
        plan = self._require(plan_id)
        if plan.status is PlanStatus.DRAFT:
            plan = self.accept_plan(plan_id)
        if plan.status is PlanStatus.ACCEPTED:
            plan = self._mark_plan_status(plan_id, plan, PlanStatus.RUNNING)
            self.events.record(
                plan_id=plan_id, node_id=None, event_type="plan_running", outcome="running",
            )
        if plan.status is not PlanStatus.RUNNING:
            return plan

        started = self._monotonic()
        while True:
            plan = self._require(plan_id)
            if plan.status is not PlanStatus.RUNNING:
                return plan
            elapsed = self._monotonic() - started
            if elapsed > plan.budgets.max_wall_clock_seconds:
                return await self.cancel_plan(
                    plan_id, reason="wall_clock_budget_exceeded", cancel_plan_status=PlanStatus.FAILED,
                )
            progressed = await self._step_plan(plan_id)
            if progressed is None:
                plan = self._require(plan_id)
                if any(
                    node.status in {NodeStatus.RUNNING, NodeStatus.SCHEDULED}
                    for node in plan.nodes
                ):
                    raise OrchestrationSchedulerError(
                        "The scheduler stopped while a task was still active; the run "
                        "requires approval or resumption."
                    )
                return self._finalize(plan_id, plan)

    async def resume_plan(self, plan_id: str, *, run_id: str) -> object:
        """Resume scheduling after an explicitly resumed child run reaches a terminal state.

        The caller must first authorize/decide any approval, clear the run's
        pending approval pointer, and execute that exact child run through the
        Agent Runtime. This method only reconciles its persisted outcome and
        continues the existing plan; it never starts or re-executes a child run.
        """
        plan = self._require(plan_id)
        node = next((item for item in plan.nodes if item.run_id == run_id), None)
        if plan.status is not PlanStatus.RUNNING:
            if (
                node is not None
                and node.status in {NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.CANCELLED}
                and plan.status in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}
            ):
                return plan
            raise OrchestrationSchedulerError(
                "Only a running plan can resume a child run."
            )
        if node is None:
            raise OrchestrationSchedulerError(
                "The child run does not belong to this plan."
            )
        if node.status not in {NodeStatus.RUNNING, NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.CANCELLED}:
            raise OrchestrationSchedulerError(
                "The plan node is not in a resumable state."
            )
        run = self.lifecycle.get_run(run_id)
        if run.owner_id != plan.owner_id:
            raise OrchestrationSchedulerError(
                "The child run owner does not match the plan owner."
            )
        if run.status in {AgentRunStatus.PAUSED, AgentRunStatus.PENDING, AgentRunStatus.RUNNING}:
            raise OrchestrationSchedulerError(
                "The child run must be explicitly resumed and reach a terminal state first."
            )
        if node.status is NodeStatus.RUNNING:
            self._map_run_outcome(plan, node.node_id, run)
        # A repeated call for an already-reconciled run is idempotent: the
        # terminal node is not mapped again, and only still-pending nodes run.
        return await self.run_plan(plan_id)

    async def _step_plan(self, plan_id: str):
        """Run one deterministic sequential scheduling step.

        Returns the node handled, or None when no node is eligible this step.
        """
        plan = self._require(plan_id)
        node_states = {node.node_id: node for node in plan.nodes}
        order = []
        from core.orchestration.graph import topological_order

        for node_id in topological_order(plan):
            node = node_states[node_id]
            if node.status is NodeStatus.PENDING and self._any_prerequisite_terminal_failure(plan, node_id, node_states):
                self._propagate_failed_prerequisite(plan, node)
                return node
        for node_id in topological_order(plan):
            node = node_states[node_id]
            if node.status is NodeStatus.PENDING and self._prerequisite_nodes_satisfied(plan, node_id, node_states):
                order.append(node)
        if not order:
            return None
        return await self._execute_node(plan, order[0])

    def _propagate_failed_prerequisite(self, plan, node) -> None:
        """Explicit policy: dependents of a failed prerequisite are skipped."""
        self.nodes.transition(
            node.node_id,
            expected_version=self._read_node_version(node.node_id),
            status=NodeStatus.SKIPPED,
            error_code="prerequisite_unsatisfied",
            error_message="A prerequisite task did not complete.",
        )
        self.events.record(
            plan_id=plan.plan_id,
            node_id=node.node_id,
            event_type="node_skipped",
            outcome="skipped",
            metadata={"reason_code": "prerequisite_unsatisfied"},
        )

    def _node_version(self, node_id: str) -> int:
        # The version is read from persistence through a dedicated helper to
        # keep the optimistic-concurrency token authoritative.
        return self._read_node_version(node_id)

    def _read_node_version(self, node_id: str) -> int:
        record = (
            self.nodes.db.query(_record_model())
            .filter(_record_model().node_id == node_id)
            .first()
        )
        if record is None:
            raise OrchestrationSchedulerError("The node was not found.")
        return int(record.version)

    # -- node execution over the Agent Runtime -----------------------------------

    async def _execute_node(self, plan, node):
        """Assign, then execute one node through the Agent Runtime."""
        version = self._read_node_version(node.node_id)
        scheduled = self.nodes.transition(
            node.node_id, expected_version=version, status=NodeStatus.SCHEDULED,
        )
        self.events.record(
            plan_id=plan.plan_id, node_id=node.node_id,
            event_type="node_scheduled", outcome="scheduled",
        )

        assignment = self.resolver.assign(plan, scheduled)
        self.assignments.append(assignment)
        self.events.record(
            plan_id=plan.plan_id, node_id=node.node_id,
            event_type="node_assignment_" + assignment.decision,
            outcome=assignment.decision,
            metadata={
                "agent_id": assignment.agent_id,
                "agent_version": assignment.agent_version,
                "reasons": list(assignment.reasons[:5]),
            },
        )
        if assignment.decision != "assigned":
            failed = self.nodes.transition(
                node.node_id,
                expected_version=self._read_node_version(node.node_id),
                status=NodeStatus.FAILED,
                error_code="assignment_denied",
                error_message="; ".join(assignment.reasons)[:300],
            )
            self.events.record(
                plan_id=plan.plan_id, node_id=node.node_id,
                event_type="node_failed", outcome="failed",
                metadata={"reason_code": "assignment_denied"},
            )
            return node

        try:
            task = self.lifecycle.create_task(
                agent_id=assignment.agent_id,
                agent_version=assignment.agent_version,
                owner_id=plan.owner_id,
                title=node.title,
                payload=self._build_child_payload(plan, node),
                data_scopes=node.data_scopes,
            )
            run = self.lifecycle.create_run(task.task_id)
        except Exception as exc:
            self._fail_node(plan, node.node_id, "task_creation_failed", str(exc)[:300])
            return node
        running = self.nodes.transition(
            node.node_id,
            expected_version=self._read_node_version(node.node_id),
            status=NodeStatus.RUNNING,
            run_id=run.run_id,
            attempts=(node.attempts or 0) + 1,
        )
        self.events.record(
            plan_id=plan.plan_id, node_id=node.node_id,
            event_type="node_running", outcome="running",
            metadata={"run_id": run.run_id, "task_id": task.task_id},
        )

        try:
            run = await self.controller.execute(run.run_id)
        except Exception as exc:
            self._fail_node(plan, node.node_id, "execution_error", str(exc)[:300])
            return node
        finally:
            if self.lifecycle.has_executor(run.run_id):
                self.lifecycle.release_executor(run.run_id)
        return self._map_run_outcome(plan, node.node_id, run)

    def _build_child_payload(self, plan, node) -> dict:
        """Compose the child task payload; also records the model-transmission authorization.

        The plan scheduler never expands scope: allowed_tools and data scopes in
        the payload are the node's declared, goal-validated scopes only.
        """
        payload = {
            "plan_id": plan.plan_id,
            "node_id": node.node_id,
            "goal_id": plan.goal_id,
            # Top-level query: the Phase 6 context builder binds the task
            # request from payload["query"], so it must not be nested only in
            # task_input.
            "query": str(node.payload.get("query", ""))[:2000],
            "acceptance": {
                "kind": node.acceptance.kind,
                "description": node.acceptance.description,
                "min_results": node.acceptance.min_results,
            },
            "task_input": dict(node.payload),
            "allow_model_transmission": False,
        }
        try:
            child = self.handoff_manager.load_inputs(plan.plan_id, node.node_id)
        except Exception:
            child = {}
        if child:
            payload["upstream_context"] = child
        return payload

    def _fail_node(self, plan, node_id: str, error_code: str, error_message: str) -> None:
        version = self._read_node_version(node_id)
        record = self.nodes.db.query(_record_model()).filter(
            _record_model().node_id == node_id
        ).first()
        status = NodeStatus(record.status) if record is not None else NodeStatus.PENDING
        if status in {NodeStatus.SCHEDULED, NodeStatus.RUNNING}:
            self.nodes.transition(
                node_id, expected_version=version, status=NodeStatus.FAILED,
                error_code=error_code, error_message=error_message,
            )
        self.events.record(
            plan_id=plan.plan_id, node_id=node_id,
            event_type="node_failed", outcome="failed",
            metadata={"reason_code": error_code},
        )

    # -- terminal mapping ---------------------------------------------------------

    def _map_run_outcome(self, plan, node_id: str, run):
        node = self.nodes.get(node_id, plan.owner_id)
        if run.status is AgentRunStatus.SUCCEEDED:
            self.handoff_manager.record_outcome(plan, node, run)
            self.nodes.transition(
                node_id,
                expected_version=self._read_node_version(node_id),
                status=NodeStatus.COMPLETED,
                error_code=None,
                error_message=None,
            )
            self._mark_dependencies(plan, node_id, DependencyStatus.SATISFIED)
            self.events.record(
                plan_id=plan.plan_id, node_id=node_id,
                event_type="node_completed", outcome="completed",
                metadata={"run_id": run.run_id},
            )
            return node
        if run.status is AgentRunStatus.CANCELLED:
            self.nodes.transition(
                node_id,
                expected_version=self._read_node_version(node_id),
                status=NodeStatus.CANCELLED,
                error_code="cancelled",
                error_message="The child run was cancelled.",
            )
            self._mark_dependencies(plan, node_id, DependencyStatus.UNSATISFIABLE)
            self._cancel_descendants(plan, node_id)
            self.events.record(
                plan_id=plan.plan_id, node_id=node_id,
                event_type="node_cancelled", outcome="cancelled",
                metadata={"run_id": run.run_id},
            )
            return node
        if run.status is AgentRunStatus.PAUSED:
            # The child paused (approval required or interruption). The plan
            # stays RUNNING; the paused node keeps its run_id so a later resume
            # reconciles truthfully without duplicate execution.
            self.events.record(
                plan_id=plan.plan_id, node_id=node_id,
                event_type="node_paused", outcome="paused",
                metadata={"run_id": run.run_id},
            )
            return node
        # Failure with bounded retries.
        attempts = node.attempts
        if attempts <= node.max_retries and attempts < 3:
            retried = self.nodes.transition(
                node_id,
                expected_version=self._read_node_version(node_id),
                status=NodeStatus.PENDING,
                error_code=run.error_code or "child_run_failed",
                error_message=(run.error_message or "")[:300],
            )
            self.events.record(
                plan_id=plan.plan_id, node_id=node_id,
                event_type="node_retry_pending", outcome="pending",
                metadata={"attempt": attempts, "reason_code": run.error_code or "child_run_failed"},
            )
            return retried
        self.nodes.transition(
            node_id,
            expected_version=self._read_node_version(node_id),
            status=NodeStatus.FAILED,
            error_code=run.error_code or "child_run_failed",
            error_message=(run.error_message or "")[:300],
        )
        self._mark_dependencies(plan, node_id, DependencyStatus.UNSATISFIABLE)
        self.events.record(
            plan_id=plan.plan_id, node_id=node_id,
            event_type="node_failed", outcome="failed",
            metadata={"run_id": run.run_id, "reason_code": run.error_code or "child_run_failed"},
        )
        return node

    def _mark_dependencies(self, plan, node_id: str, status: DependencyStatus) -> None:
        for dependency in plan.dependencies:
            if dependency.depends_on == node_id and dependency.status is DependencyStatus.PENDING:
                self.plans.set_dependency_status(dependency.dependency_id, status)

    def _cancel_descendants(self, plan, node_id: str) -> None:
        """Propagate cancellation to pending descendants (explicit policy)."""
        from core.orchestration.graph import build_dependents

        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for dependent in build_dependents(plan).get(current, []):
                node = next((item for item in self._require(plan.plan_id).nodes if item.node_id == dependent), None)
                if node is None or node.status is not NodeStatus.PENDING:
                    continue
                version = self._read_node_version(dependent)
                self.nodes.transition(
                    dependent, expected_version=version,
                    status=NodeStatus.CANCELLED,
                    error_code="ancestor_cancelled",
                    error_message="An ancestor task was cancelled.",
                )
                self._mark_dependencies(plan, dependent, DependencyStatus.UNSATISFIABLE)
                self.events.record(
                    plan_id=plan.plan_id, node_id=dependent,
                    event_type="node_cancelled", outcome="cancelled",
                    metadata={"reason_code": "ancestor_cancelled"},
                )
                frontier.append(dependent)

    # -- cancellation and recovery ---------------------------------------------------

    async def cancel_plan(self, plan_id: str, *, reason: str = "requested_by_owner", cancel_plan_status=PlanStatus.CANCELLED) -> object:
        """Cancel a plan and propagate the cancellation to its tasks."""
        plan = self._require(plan_id)
        for node in plan.nodes:
            if node.status in {NodeStatus.PENDING, NodeStatus.SCHEDULED}:
                try:
                    self.nodes.transition(
                        node.node_id,
                        expected_version=self._read_node_version(node.node_id),
                        status=NodeStatus.CANCELLED,
                        error_code="plan_cancelled",
                        error_message=reason[:300],
                    )
                    self.events.record(
                        plan_id=plan_id, node_id=node.node_id,
                        event_type="node_cancelled", outcome="cancelled",
                        metadata={"reason_code": reason},
                    )
                except Exception:
                    continue
        for node in plan.nodes:
            if node.status is NodeStatus.RUNNING and node.run_id:
                try:
                    run = self.lifecycle.get_run(node.run_id)
                except Exception:
                    run = None
                if run is not None and run.status in {
                    AgentRunStatus.PENDING, AgentRunStatus.RUNNING, AgentRunStatus.PAUSED,
                }:
                    try:
                        await self.lifecycle.cancel(
                            node.run_id,
                            expected_version=run.version,
                            reason=reason[:200],
                        )
                    except Exception:
                        pass
                try:
                    self.nodes.transition(
                        node.node_id,
                        expected_version=self._read_node_version(node.node_id),
                        status=NodeStatus.CANCELLED,
                        error_code="plan_cancelled",
                        error_message=reason[:300],
                    )
                except Exception:
                    pass
        updated = self._require(plan_id)
        try:
            self.plans.transition(
                plan_id, expected_version=updated.version,
                status=cancel_plan_status,
            )
            self.events.record(
                plan_id=plan_id, node_id=None,
                event_type="plan_" + cancel_plan_status.value, outcome=cancel_plan_status.value,
                metadata={"reason_code": reason},
            )
        except Exception:
            pass
        return self._require(plan_id)

    def reconcile_plan(self, plan_id: str) -> object:
        """Restart recovery: reconcile active nodes with their child run state.

        No scheduled work is silently re-executed: a SCHEDULED node without a
        child run returns to PENDING, a RUNNING node whose child run is paused
        keeps its run_id for an explicit resume, and a child run that already
        finished maps its truthful terminal outcome.
        """
        plan = self._require(plan_id)
        for node in plan.nodes:
            if node.status is NodeStatus.SCHEDULED and not node.run_id:
                self.nodes.transition(
                    node.node_id,
                    expected_version=self._read_node_version(node.node_id),
                    status=NodeStatus.PENDING,
                )
                self.events.record(
                    plan_id=plan_id, node_id=node.node_id,
                    event_type="node_reconciled", outcome="pending",
                    metadata={"reason_code": "scheduled_without_run"},
                )
            elif node.status is NodeStatus.RUNNING and node.run_id:
                run = self.lifecycle.runs.get(node.run_id)
                if run is None:
                    self.nodes.transition(
                        node.node_id,
                        expected_version=self._read_node_version(node.node_id),
                        status=NodeStatus.PENDING,
                        error_code="restart_recovery",
                        error_message="The child run is missing; the node was not re-executed.",
                    )
                elif run.status is AgentRunStatus.PAUSED:
                    self.events.record(
                        plan_id=plan_id, node_id=node.node_id,
                        event_type="node_reconciled", outcome="paused",
                        metadata={"run_id": run.run_id},
                    )
                elif run.status in {
                    AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED,
                }:
                    self._map_run_outcome(plan, node.node_id, run)
        return self._require(plan_id)

    def _finalize(self, plan_id: str, plan) -> object:
        aggregate = self.aggregator.aggregate(plan)
        outcome = {
            "aggregate_status": aggregate.status,
            "outcomes": list(aggregate.outcomes),
            "conflicts": list(aggregate.conflicts),
            "missing_evidence": list(aggregate.missing_evidence),
        }
        target = PlanStatus.COMPLETED
        if aggregate.status == "failed":
            target = PlanStatus.FAILED
        elif aggregate.status == "cancelled":
            target = PlanStatus.FAILED
        elif any(item.get("status") not in {"completed", "skipped"} for item in aggregate.outcomes):
            target = PlanStatus.FAILED
        try:
            plan = self.plans.transition(
                plan_id, expected_version=plan.version, status=target,
            )
        except Exception:
            plan = self._require(plan_id)
        self.events.record(
            plan_id=plan_id, node_id=None,
            event_type="plan_" + target.value, outcome=target.value,
            metadata={"aggregate_status": aggregate.status},
        )
        return plan


def _record_model():
    from core.orchestration.models import OrchestrationNodeRecord

    return OrchestrationNodeRecord
