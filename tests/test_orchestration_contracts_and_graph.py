"""WP-7.1 tests: orchestration contracts, state tables, and the graph validator."""
from __future__ import annotations

import pytest

from core.agents.contracts import CompletionCriteria, DataScope
from core.orchestration.contracts import (
    MAX_PLAN_NODES,
    Assignment,
    Dependency,
    DependencyStatus,
    Evidence,
    Goal,
    Handoff,
    NodeStatus,
    OrchestrationBudgets,
    OrchestrationNodeStateError,
    Plan,
    PlanStatus,
    PlanValidationError,
    TaskNode,
    AggregateResult,
    new_dependency_id,
    new_goal_id,
    new_handoff_id,
    new_node_id,
    new_plan_id,
    can_transition_dependency,
    can_transition_node,
    require_node_transition,
)
from core.orchestration.graph import (
    build_dependents,
    build_prerequisites,
    topological_order,
    validate_plan,
)

OWNER_ID = "local-user"


def make_scope(scope_id="goal-scope"):
    return DataScope("knowledge", "user", scope_id, OWNER_ID)


def make_budgets(**overrides):
    return OrchestrationBudgets(**overrides)


def make_node(
    plan_id,
    *,
    ordinal=0,
    title="Analyze scope",
    capabilities=("knowledge_search",),
    payload=None,
    **kwargs,
):
    # payload is an explicit keyword argument: forwarding it through **kwargs
    # as well would pass it to TaskNode more than once.
    return TaskNode(
        node_id=new_node_id(),
        plan_id=plan_id,
        ordinal=ordinal,
        title=title,
        required_capabilities=capabilities,
        acceptance=CompletionCriteria(
            kind="structured_result_present",
            description="A structured result was reported.",
        ),
        payload=payload if payload is not None else {"query": "durable storage"},
        data_scopes=(make_scope(),),
        tool_scopes=("knowledge_search",),
        **kwargs,
    )


def make_plan(
    budgets=None,
    *,
    plan_id=None,
    goal_id=None,
    parent_run_id=None,
    nodes=None,
    dependencies=None,
):
    # When nodes are supplied, the plan identifier must be the one the nodes
    # already reference so structural validation sees a consistent plan; a
    # freshly generated id would reject every graph fixture prematurely.
    if plan_id is None:
        plan_id = nodes[0].plan_id if nodes else new_plan_id()
    goal_id = goal_id or new_goal_id()
    if nodes is None:
        first = make_node(plan_id, ordinal=0, title="Analyze scope")
        second = make_node(plan_id, ordinal=1, title="Summarize findings")
        nodes = (first, second)
        dependencies = (
            Dependency(
                dependency_id=new_dependency_id(),
                plan_id=plan_id,
                node_id=second.node_id,
                depends_on=first.node_id,
            ),
        )
    return Plan(
        plan_id=plan_id,
        goal_id=goal_id,
        parent_run_id=parent_run_id or ("a" * 32),
        parent_task_id="b" * 32,
        owner_id=OWNER_ID,
        revision=0,
        status=PlanStatus.DRAFT,
        nodes=nodes,
        dependencies=tuple(dependencies or ()),
        budgets=budgets or make_budgets(),
    )


def make_goal(*, tool_scopes=("knowledge_search",)):
    return Goal(
        goal_id=new_goal_id(),
        owner_id=OWNER_ID,
        description="Analyze the bound knowledge scope.",
        success_criteria="At least one structured analysis is reported.",
        data_scopes=(make_scope(),),
        tool_scopes=tuple(tool_scopes),
    )


class TestContracts:
    def test_goal_rejects_foreign_data_scope(self):
        foreign = DataScope("knowledge", "user", "goal-scope", "someone-else")
        with pytest.raises(PlanValidationError):
            Goal(
                goal_id=new_goal_id(),
                owner_id=OWNER_ID,
                description="Analyze the bound knowledge scope.",
                success_criteria="At least one analysis is reported.",
                data_scopes=(foreign,),
                tool_scopes=("knowledge_search",),
            )

    def test_goal_rejects_wildcard_identifier(self):
        with pytest.raises(PlanValidationError):
            Goal(
                goal_id=new_goal_id(),
                owner_id="*",
                description="Analyze the bound knowledge scope.",
                success_criteria="At least one analysis is reported.",
            )

    def test_task_node_rejects_oversized_payload(self):
        with pytest.raises(PlanValidationError):
            make_node(new_plan_id(), payload={"blob": "x" * (32 * 1024 + 1)})

    def test_valid_assignment_is_accepted(self):
        plan = make_plan()
        assignment = Assignment(
            assignment_id=new_goal_id(),
            plan_id=plan.plan_id,
            node_id=plan.nodes[0].node_id,
            decision="assigned",
            agent_id="knowledge-analyzer",
            agent_version="1.0.0",
            reasons=("The definition declares knowledge_search.",),
            evidence=(
                Evidence(
                    evidence_id=new_goal_id(),
                    kind="verified_tool",
                    subject="knowledge-analyzer:1.0.0",
                    claim="knowledge_search is registered and read-only verified.",
                ),
            ),
        )
        assert assignment.decision == "assigned" and len(assignment.evidence) == 1

    def test_assignment_without_agent_is_rejected(self):
        plan = make_plan()
        with pytest.raises(PlanValidationError):
            Assignment(
                assignment_id=new_goal_id(),
                plan_id=plan.plan_id,
                node_id=plan.nodes[0].node_id,
                decision="assigned",
            )

    def test_handoff_rejects_wrong_envelope_version(self):
        with pytest.raises(Exception, match="envelope"):
            Handoff(
                handoff_id=new_handoff_id(),
                plan_id=new_plan_id(),
                node_id=new_node_id(),
                from_run_id="c" * 32,
                envelope_version="orchestration.handoff/99",
                payload={"results": []},
                status="complete",
            )


class TestStateTables:
    def test_node_transitions_follow_table(self):
        assert can_transition_node(NodeStatus.PENDING, NodeStatus.SCHEDULED)
        assert not can_transition_node(NodeStatus.PENDING, NodeStatus.COMPLETED)
        with pytest.raises(OrchestrationNodeStateError):
            require_node_transition(NodeStatus.PENDING, NodeStatus.COMPLETED)

    def test_terminal_nodes_absorb(self):
        for terminal in (NodeStatus.COMPLETED, NodeStatus.SKIPPED):
            assert not can_transition_node(terminal, NodeStatus.PENDING)

    def test_dependency_states_reach_unsatisfiable_once(self):
        assert can_transition_dependency(DependencyStatus.PENDING, DependencyStatus.UNSATISFIABLE)
        assert not can_transition_dependency(DependencyStatus.UNSATISFIABLE, DependencyStatus.PENDING)


class TestGraphValidator:
    def test_valid_plan_passes_with_goal_checks(self):
        plan = make_plan()
        goal = make_goal()
        validate_plan(plan, goal=goal)
        assert build_prerequisites(plan)[plan.nodes[1].node_id] == [plan.nodes[0].node_id]
        assert build_dependents(plan)[plan.nodes[0].node_id] == [plan.nodes[1].node_id]

    def test_diamond_graph_orders_deterministically(self):
        plan_id = new_plan_id()
        a = make_node(plan_id, ordinal=0, title="Root", capabilities=("knowledge_search",))
        b = make_node(plan_id, ordinal=1, title="Left", capabilities=("knowledge_search",))
        c = make_node(plan_id, ordinal=2, title="Right", capabilities=("knowledge_search",))
        d = make_node(plan_id, ordinal=3, title="Join", capabilities=("knowledge_search",))
        deps = lambda x, y: Dependency(new_dependency_id(), plan_id, x, y)
        plan = make_plan(nodes=(a, b, c, d), dependencies=(deps(b.node_id, a.node_id),
                                                          deps(c.node_id, a.node_id),
                                                          deps(d.node_id, b.node_id),
                                                          deps(d.node_id, c.node_id)))
        assert topological_order(plan) == (a.node_id, b.node_id, c.node_id, d.node_id)

    def test_cycle_is_rejected(self):
        plan_id = new_plan_id()
        a = make_node(plan_id, ordinal=0)
        b = make_node(plan_id, ordinal=1)
        c = make_node(plan_id, ordinal=2)
        deps = lambda x, y: Dependency(new_dependency_id(), plan_id, x, y)
        plan = make_plan(nodes=(a, b, c), dependencies=(deps(a.node_id, b.node_id),
                                                        deps(b.node_id, c.node_id),
                                                        deps(c.node_id, a.node_id)))
        with pytest.raises(PlanValidationError, match="cycle"):
            validate_plan(plan)
        with pytest.raises(PlanValidationError, match="cycle"):
            topological_order(plan)

    def test_unknown_dependency_reference_is_rejected(self):
        plan_id = new_plan_id()
        a = make_node(plan_id, ordinal=0)
        dangling = Dependency(new_dependency_id(), plan_id, a.node_id, "f" * 32)
        plan = make_plan(nodes=(a,), dependencies=(dangling,))
        with pytest.raises(PlanValidationError, match="unknown"):
            validate_plan(plan)

    def test_duplicate_node_id_is_rejected(self):
        plan_id = new_plan_id()
        a = make_node(plan_id, ordinal=0)
        twin = TaskNode(
            node_id=a.node_id,
            plan_id=plan_id,
            ordinal=1,
            title="Duplicate",
            required_capabilities=("knowledge_search",),
            acceptance=CompletionCriteria(kind="structured_result_present", description="x"),
            payload={},
        )
        plan = make_plan(nodes=(a, twin))
        with pytest.raises(PlanValidationError, match="unique"):
            validate_plan(plan)

    def test_duplicate_edge_is_rejected(self):
        plan_id = new_plan_id()
        a = make_node(plan_id, ordinal=0)
        b = make_node(plan_id, ordinal=1)
        edge = lambda: Dependency(new_dependency_id(), plan_id, b.node_id, a.node_id)
        plan = make_plan(nodes=(a, b), dependencies=(edge(), edge()))
        with pytest.raises(PlanValidationError, match="Duplicate"):
            validate_plan(plan)

    def test_node_budget_is_enforced(self):
        plan_id = new_plan_id()
        over = make_plan(budgets=make_budgets(max_nodes=1), nodes=tuple(
            make_node(plan_id, ordinal=index, title="Node " + str(index))
            for index in range(3)
        ))
        with pytest.raises(PlanValidationError, match="node budget"):
            validate_plan(over)
        assert MAX_PLAN_NODES == 32

    def test_scope_expansion_is_rejected(self):
        plan_id = new_plan_id()
        rogue = TaskNode(
            node_id=new_node_id(),
            plan_id=plan_id,
            ordinal=0,
            title="Rogue scope",
            required_capabilities=("knowledge_search",),
            acceptance=CompletionCriteria(kind="structured_result_present", description="x"),
            payload={},
            data_scopes=(DataScope("knowledge", "user", "outside-scope", OWNER_ID),),
            tool_scopes=("knowledge_search",),
        )
        plan = make_plan(nodes=(rogue,))
        goal = make_goal()
        with pytest.raises(PlanValidationError, match="outside the goal"):
            validate_plan(plan, goal=goal)

    def test_tool_scope_expansion_is_rejected(self):
        plan_id = new_plan_id()
        rogue = TaskNode(
            node_id=new_node_id(),
            plan_id=plan_id,
            ordinal=0,
            title="Rogue tool",
            required_capabilities=("knowledge_search",),
            acceptance=CompletionCriteria(kind="structured_result_present", description="x"),
            payload={},
            data_scopes=(make_scope(),),
            tool_scopes=("knowledge_write",),
        )
        plan = make_plan(nodes=(rogue,))
        goal = make_goal(tool_scopes=("knowledge_search",))
        with pytest.raises(PlanValidationError, match="outside the goal"):
            validate_plan(plan, goal=goal)

    def test_maximum_node_contract_limit(self):
        assert MAX_PLAN_NODES == 32
