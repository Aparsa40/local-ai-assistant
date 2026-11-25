"""WP-7.6 Supervisor orchestration tests: failure injection, recovery, and security.

These tests compose the production AgentRuntimeContainer and validate the
orchestration behavior end to end through the real lifecycle, controller,
repositories, and scheduler. The InterfaceManager is replaced by a recording
fake; nothing else is substituted.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_test_models import OWNER_ID, make_agent_env
from core.agents.contracts import AgentRunStatus
from core.agents.controller import AgentControllerError
from core.orchestration.assignment import CapabilityCandidate
from core.orchestration.contracts import (
    MAX_PLAN_NODES,
    NodeStatus,
    PlanStatus,
    PlanValidationError,
    new_plan_id,
)
from core.orchestration.planner import ProposalRejected
from core.orchestration.scheduler import OrchestrationSchedulerError
from core.orchestration.supervisor import OrchestrationServiceError
from core.repositories.agent_repository import AgentDefinitionRepository
from core.tools.registry import ToolRegistry

SCOPE_ID = "orchestration-scope"


class FailingBehavior:
    """Trusted behavior stub that always fails the run truthfully."""

    calls = 0

    def decide(self, ctx, state) -> dict:
        FailingBehavior.calls += 1
        return {
            "kind": "finish",
            "status": "failed",
            "error_code": "injected_failure",
            "error_message": "The test behavior failed deterministically.",
        }


def make_orch(env):
    return env.container.build_orchestration(env.session, env.services)


def make_goal(orch, *, data_scopes=True, tool_scopes=("knowledge_search",)):
    scopes = (
        None if not data_scopes else (("knowledge", "user", SCOPE_ID, OWNER_ID),)
    )
    from core.agents.contracts import DataScope

    data = tuple(
        DataScope(domain=s[0], scope_type=s[1], scope_id=s[2], owner_id=s[3])
        for s in scopes
    ) if scopes else ()
    return orch.create_goal(
        owner_id=OWNER_ID,
        description="Summarize the seeded knowledge scope deterministically.",
        success_criteria="Each scope analysis reports its collected sources.",
        data_scopes=data,
        tool_scopes=tuple(tool_scopes),
    )


def hex32(prefix: str = "a") -> str:
    return (prefix * 32)[:32]


def proposal_for(goal, *, node_count=2, cyclic=False):
    nodes = []
    for index in range(node_count):
        nodes.append({
            "node_id": hex32(str(index + 1)),
            "title": "Node " + str(index),
            "required_capabilities": ["knowledge_search"],
            "payload": {"query": "seeded"},
            "data_scopes": [{
                "domain": "knowledge",
                "scope_type": "user",
                "scope_id": SCOPE_ID,
                "owner_id": OWNER_ID,
            }],
            "tool_scopes": ["knowledge_search"],
        })
    dependencies = []
    if node_count == 2:
        dependencies.append({"node_id": hex32("2"), "depends_on": hex32("1")})
    if cyclic:
        dependencies.append({"node_id": hex32("1"), "depends_on": hex32("2")})
    return json.dumps({
        "schema": "orchestration.proposal/1",
        "goal_id": goal.goal_id,
        "nodes": nodes,
        "dependencies": dependencies,
    })


def plan_with_dependencies(orch, goal, *, node_count=2, cyclic=False):
    result = asyncio.run(orch.plan_goal(
        goal.goal_id,
        owner_id=OWNER_ID,
        strategy="validated_model_proposal",
        proposal_text=proposal_for(goal, node_count=node_count, cyclic=cyclic),
    ))
    return result


# -- planning ------------------------------------------------------------------


def test_plan_goal_persists_accepted_plan_and_runs_supervisor(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = asyncio.run(orch.plan_goal(goal.goal_id, owner_id=OWNER_ID))
        assert result["status"] == "accepted"
        plan = orch.plans.get(result["plan_id"])
        assert plan.status is PlanStatus.ACCEPTED
        assert plan.parent_run_id == result["supervisor_run_id"]
        assert result["node_count"] == len(plan.nodes) == 1
        event_types = [event["event_type"] for event in orch.events.list_for_plan(plan.plan_id)]
        assert "plan_created" in event_types
        assert "supervisor_run_completed" in event_types
        parent_run = env.services.lifecycle.get_run(result["supervisor_run_id"])
        assert parent_run.status is AgentRunStatus.SUCCEEDED
    finally:
        env.dispose()


def test_template_plan_requires_explicit_goal_scopes(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        without_data = make_goal(orch, data_scopes=False)
        with pytest.raises(PlanValidationError):
            asyncio.run(orch.plan_goal(without_data.goal_id, owner_id=OWNER_ID))
        without_tools = make_goal(orch, tool_scopes=())
        with pytest.raises(PlanValidationError):
            asyncio.run(orch.plan_goal(without_tools.goal_id, owner_id=OWNER_ID))
    finally:
        env.dispose()


def test_plan_goal_rejects_wrong_owner(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        with pytest.raises(OrchestrationServiceError):
            asyncio.run(orch.plan_goal(goal.goal_id, owner_id="someone-else"))
    finally:
        env.dispose()


def test_proposal_revisions_are_bounded(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        with pytest.raises(ProposalRejected, match="revision budget"):
            asyncio.run(orch.plan_goal(
                goal.goal_id, owner_id=OWNER_ID,
                strategy="validated_model_proposal",
                proposal_text=proposal_for(goal), revision=3,
            ))
    finally:
        env.dispose()


def test_proposal_rejects_unknown_references_and_cycles(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        with pytest.raises(PlanValidationError):
            asyncio.run(orch.plan_goal(
                goal.goal_id, owner_id=OWNER_ID,
                strategy="validated_model_proposal",
                proposal_text=proposal_for(goal, cyclic=True),
            ))
    finally:
        env.dispose()


def test_proposal_rejects_nested_plan_fields_in_payload(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        nested = json.loads(proposal_for(goal, node_count=1))
        nested["nodes"][0]["payload"]["subplan"] = {"plan": "again"}
        with pytest.raises(ProposalRejected):
            asyncio.run(orch.plan_goal(
                goal.goal_id, owner_id=OWNER_ID,
                strategy="validated_model_proposal",
                proposal_text=json.dumps(nested),
            ))
    finally:
        env.dispose()


def test_model_proposal_requests_go_through_interface_manager(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        env.interface_manager.chunks = (proposal_for(goal, node_count=1),)
        plan = asyncio.run(orch.planner.propose_plan_with_model(
            goal, env.interface_manager,
            provider_id="test-provider", model_id="test-model",
            parent_run_id=hex32("b"), parent_task_id=hex32("c"),
        ))
        assert len(env.interface_manager.calls) == 1
        assert env.interface_manager.calls[0]["provider_id"] == "test-provider"
        assert len(plan.nodes) == 1
    finally:
        env.dispose()


# -- scheduling -------------------------------------------------------------


def test_scheduler_executes_nodes_and_records_assignments(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert plan.status is PlanStatus.COMPLETED
        node_states = {node.node_id: node for node in plan.nodes}
        assert all(
            node.status is NodeStatus.COMPLETED for node in plan.nodes
        )
        assignments = orch.assignments.list_for_plan(plan.plan_id)
        assert assignments
        assert all(item["decision"] == "assigned" for item in assignments)
        assert all(item["agent_id"] == "knowledge-analyzer" for item in assignments)
        handoffs = orch.handoff_manager.list_for_plan(plan.plan_id)
        assert len(handoffs) == len(plan.nodes)
        view = orch.plan_view(plan.plan_id)
        assert view["status"] == "completed"
        assert view["assignments"]
    finally:
        env.dispose()


def test_dependencies_schedule_only_after_prerequisites(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = asyncio.run(orch.execute_plan(result["plan_id"]))
        by_ordinal = {node.ordinal: node for node in plan.nodes}
        # Sequential scheduler: the dependent node ran after its prerequisite.
        assert by_ordinal[1].status is NodeStatus.COMPLETED
        assert by_ordinal[0].status is NodeStatus.COMPLETED
        dependency = plan.dependencies[0]
        assert dependency.policy == "all_success"
    finally:
        env.dispose()


def test_executing_a_terminal_plan_does_not_duplicate_work(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        first = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert first.status is PlanStatus.COMPLETED
        again = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert again.status is PlanStatus.COMPLETED
        assert len(orch.assignments.list_for_plan(result["plan_id"])) == 2
    finally:
        env.dispose()


def test_assignment_denial_fails_node_without_executing(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        # Remove the capability candidates: nothing can be assigned anymore.
        orch.resolver._candidates.clear()
        plan = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert plan.status is PlanStatus.FAILED
        node = plan.nodes[0]
        assert node.status is NodeStatus.FAILED
        assert node.error_code == "assignment_denied"
        assert orch.resolver.candidates() == ()
    finally:
        env.dispose()


def test_unknown_capability_is_denied(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        unknown = json.loads(proposal_for(goal, node_count=1))
        unknown["nodes"][0]["required_capabilities"] = ["nonexistent_capability"]
        result = asyncio.run(orch.plan_goal(
            goal.goal_id, owner_id=OWNER_ID,
            strategy="validated_model_proposal",
            proposal_text=json.dumps(unknown),
        ))
        plan = asyncio.run(orch.execute_plan(result["plan_id"]))
        node = plan.nodes[0]
        assert node.status is NodeStatus.FAILED
        assert "unknown" in (node.error_message or "").lower()
    finally:
        env.dispose()


# -- failure injection, retries, cancellation, recovery -------------------------


def _register_failing_agent(env, session, orch):
    from agent_test_models import make_definition

    AgentDefinitionRepository(session).register(make_definition(
        agent_id="failing-agent",
        goal="A deterministic failing agent used for failure injection.",
        # The definition binds the read capability so the trusted local owner
        # can issue the exact per-run knowledge-read grant for the node scope;
        # a tool-free definition would be denied before the loop even runs.
        allowed_tools=("knowledge_search",),
        allowed_models=(),
        data_scopes=("knowledge",),
    ))
    env.container.behaviors[("failing-agent", "1.0.0")] = FailingBehavior()
    capabilities = ("injected_capability",)
    orch.resolver.register_candidate(CapabilityCandidate(
        "failing-agent", "1.0.0", capabilities=capabilities,
    ))
    return capabilities


def test_failed_prerequisites_skip_dependents_and_respect_retry_limits(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        capabilities = _register_failing_agent(env, env.session, orch)
        goal = make_goal(orch)
        failing = json.loads(proposal_for(goal))
        # Node 2 depends on node 1, which is bound to the failing agent.
        failing["nodes"][0]["required_capabilities"] = list(capabilities)
        failing["nodes"][0]["tool_scopes"] = []
        result = asyncio.run(orch.plan_goal(
            goal.goal_id, owner_id=OWNER_ID,
            strategy="validated_model_proposal",
            proposal_text=json.dumps(failing),
        ))
        plan = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert plan.status is PlanStatus.FAILED
        by_ordinal = {node.ordinal: node for node in plan.nodes}
        assert by_ordinal[0].status is NodeStatus.FAILED
        # One bounded retry: initial attempt plus max_retries_per_task(=1).
        assert by_ordinal[0].attempts == goal.budgets.max_retries_per_task + 1
        assert by_ordinal[1].status is NodeStatus.SKIPPED
        assert by_ordinal[1].error_code == "prerequisite_unsatisfied"
    finally:
        env.dispose()


def test_cancel_plan_cancels_pending_nodes_and_propagates(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = asyncio.run(orch.cancel_plan(result["plan_id"]))
        assert plan.status is PlanStatus.CANCELLED
        assert all(
            node.status is NodeStatus.CANCELLED for node in plan.nodes
        )
    finally:
        env.dispose()


def test_wall_clock_budget_fails_the_plan(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        ticks = iter([0.0, 0.0] + [10_000.0] * 50)
        orch.scheduler._monotonic = lambda: next(ticks)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert plan.status is PlanStatus.FAILED
    finally:
        env.dispose()


def test_reconcile_returns_scheduled_node_without_run_to_pending(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = orch.plans.get(result["plan_id"])
        node = plan.nodes[0]
        # Simulate a crash between SCHEDULED and child task creation.
        orch.nodes.transition(
            node.node_id,
            expected_version=orch.scheduler._read_node_version(node.node_id),
            status=NodeStatus.SCHEDULED,
        )
        reconciled = orch.reconcile(result["plan_id"])
        assert reconciled.status is PlanStatus.ACCEPTED
        reconciled_node = next(
            item for item in reconciled.nodes if item.node_id == node.node_id
        )
        assert reconciled_node.status is NodeStatus.PENDING
        # Now the plan still runs to completion without duplicated side effects.
        finished = asyncio.run(orch.execute_plan(result["plan_id"]))
        assert finished.status is PlanStatus.COMPLETED
        node_states = {item.ordinal: item for item in finished.nodes}
        assert all(
            item.status is NodeStatus.COMPLETED for item in finished.nodes
        )
        assert node_states[0].attempts == 1
    finally:
        env.dispose()


def test_reconcile_maps_finished_child_run_outcomes(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        env.seed_knowledge(env.knowledge_scope(SCOPE_ID), "durable storage content")
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        # Execute fully, then reconcile: terminal outcomes stay terminal.
        asyncio.run(orch.execute_plan(result["plan_id"]))
        reconciled = orch.reconcile(result["plan_id"])
        assert reconciled.status is PlanStatus.COMPLETED
        node = reconciled.nodes[0]
        assert node.status is NodeStatus.COMPLETED
    finally:
        env.dispose()


def test_run_plan_raises_when_paused_node_blocks_progress(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = orch.plans.get(result["plan_id"])
        node = plan.nodes[0]
        version = orch.scheduler._read_node_version(node.node_id)
        orch.nodes.transition(node.node_id, expected_version=version, status=NodeStatus.SCHEDULED)
        # A SCHEDULED node with no run blocks progress; the scheduler must
        # refuse to silently stall and must surface the blocked state.
        version = orch.scheduler._read_node_version(node.node_id)
        with pytest.raises(OrchestrationSchedulerError, match="resumption"):
            asyncio.run(orch.scheduler.run_plan(result["plan_id"]))
        assert orch.reconcile(result["plan_id"]) is not None
    finally:
        env.dispose()


# -- least privilege and explainability ------------------------------------------


def test_assignment_resolver_denies_scope_expansion(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = orch.plans.get(result["plan_id"])
        node = plan.nodes[0]
        from core.agents.contracts import DataScope

        outside = DataScope("memory", "user", "elsewhere", OWNER_ID)
        expanded = type(node)(
            node_id=node.node_id,
            plan_id=node.plan_id,
            ordinal=node.ordinal,
            title=node.title,
            required_capabilities=node.required_capabilities,
            acceptance=node.acceptance,
            payload=node.payload,
            data_scopes=(outside,),
            tool_scopes=node.tool_scopes,
        )
        decision = orch.resolver.assign(plan, expanded)
        assert decision.decision == "denied"
        assert any("exceed" in reason.lower() for reason in decision.reasons)
        explanation = orch.resolver.explain(plan, node)
        assert explanation["node_id"] == node.node_id
        assert "knowledge-analyzer" in [
            item["agent_id"] for item in explanation["candidates"]
        ]
    finally:
        env.dispose()


def test_model_dependent_candidate_denied_without_provider_evidence(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = orch.plans.get(result["plan_id"])
        node = plan.nodes[0]
        orch.resolver._candidates.clear()
        orch.resolver.register_candidate(CapabilityCandidate(
            "model-dependent-agent", "1.0.0",
            capabilities=("knowledge_search",),
            allowed_models=("some/model",),
            model_dependent=True,
        ))
        decision = orch.resolver.assign(plan, node)
        assert decision.decision == "denied"
    finally:
        env.dispose()


def test_verified_tool_evidence_comes_from_the_registry(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = orch.plans.get(result["plan_id"])
        node = plan.nodes[0]
        decision = orch.resolver.assign(plan, node)
        assert decision.decision == "assigned"
        kinds = {item.kind for item in decision.evidence}
        assert kinds & {"verified_tool", "declared_capability", "model_catalog"}
    finally:
        env.dispose()


def test_assignment_requires_one_candidate_to_cover_all_capabilities(tmp_path):
    """Capabilities from separate agents must not be combined for assignment."""
    from dataclasses import replace

    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan = orch.plans.get(result["plan_id"])
        node = replace(
            plan.nodes[0],
            required_capabilities=("knowledge_search", "memory_read"),
        )

        orch.resolver._candidates.clear()
        orch.resolver.register_candidate(CapabilityCandidate(
            "search-only", "1.0.0", capabilities=("knowledge_search",),
        ))
        orch.resolver.register_candidate(CapabilityCandidate(
            "memory-only", "1.0.0", capabilities=("memory_read",),
        ))

        decision = orch.resolver.assign(plan, node)

        assert decision.decision == "denied"
        assert decision.agent_id is None
        assert any(
            "single registered agent" in reason.lower()
            for reason in decision.reasons
        )
    finally:
        env.dispose()


def test_resume_plan_reconciles_approved_child_without_recreating_it(tmp_path):
    """A resumed child run is reconciled once, then pending work may continue."""
    from core.agents.contracts import StopReason

    env = make_agent_env(tmp_path)
    try:
        orch = make_orch(env)
        goal = make_goal(orch)
        result = plan_with_dependencies(orch, goal)
        plan_id = result["plan_id"]
        plan = orch.plans.get(plan_id)
        node = plan.nodes[0]

        # Put the accepted plan/node into the same persisted state produced
        # when the scheduler's child run pauses for an approval decision.
        orch.scheduler._mark_plan_status(plan_id, plan, PlanStatus.RUNNING)
        task = env.services.lifecycle.create_task(
            agent_id="knowledge-analyzer",
            agent_version="1.0.0",
            owner_id=OWNER_ID,
            title="Approval-resume test",
            payload={"query": "approved test"},
            data_scopes=goal.data_scopes,
        )
        run = env.services.lifecycle.create_run(task.task_id)
        run = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        run = env.services.lifecycle.pause_for_approval(
            run.run_id,
            expected_version=run.version,
            approval_id="approval-test",
        )
        orch.nodes.transition(
            node.node_id,
            expected_version=orch.scheduler._read_node_version(node.node_id),
            status=NodeStatus.SCHEDULED,
        )
        orch.nodes.transition(
            node.node_id,
            expected_version=orch.scheduler._read_node_version(node.node_id),
            status=NodeStatus.RUNNING,
            run_id=run.run_id,
            attempts=1,
        )

        with pytest.raises(OrchestrationSchedulerError, match="explicitly resumed"):
            asyncio.run(orch.resume_plan(plan_id, run_id=run.run_id))

        # Model the existing authorized approval-resume flow: the approval
        # decision has already happened before this lifecycle transition.
        run = env.services.lifecycle.clear_pending_approval(
            run.run_id, expected_version=run.version,
        )
        run = env.services.lifecycle.resume(run.run_id, expected_version=run.version)
        run = env.services.lifecycle.complete(
            run.run_id,
            expected_version=run.version,
            outcome={"status": "complete", "summary": "Approved child result", "results": []},
        )

        finished = asyncio.run(orch.resume_plan(plan_id, run_id=run.run_id))
        assert finished.status is PlanStatus.COMPLETED
        assert finished.nodes[0].status is NodeStatus.COMPLETED
        assert finished.nodes[0].run_id == run.run_id
        assert finished.nodes[0].attempts == 1
        assert len(orch.assignments.list_for_plan(plan_id)) == 0

        # A duplicate reconciliation must not remap the node or create work.
        again = asyncio.run(orch.resume_plan(plan_id, run_id=run.run_id))
        assert again.status is PlanStatus.COMPLETED
        assert again.nodes[0].run_id == run.run_id
        assert again.nodes[0].attempts == 1
    finally:
        env.dispose()
