"""Deterministic dependency-graph representation and validation for plans.

The graph layer is pure and deterministic: no persistence, scheduling, model
calls, or permissions live here. A plan that fails validation is never
persisted or scheduled (WP-7.1 exit criterion).
"""
from __future__ import annotations

from core.orchestration.contracts import (
    MAX_PLAN_NODES,
    Dependency,
    Goal,
    Plan,
    PlanValidationError,
    PlanStatus,
)


def build_dependents(plan: Plan) -> dict:
    """Map each node id to the ordered list of ids that depend on it."""
    dependents: dict = {node.node_id: [] for node in plan.nodes}
    declared = {node.node_id for node in plan.nodes}
    for dependency in plan.dependencies:
        dependents[dependency.depends_on].append(dependency.node_id)
    for node_id in declared:
        dependents[node_id] = list(dependents[node_id])
    return dependents


def build_prerequisites(plan: Plan) -> dict:
    """Map each node id to the ordered list of ids it depends on."""
    prerequisites: dict = {node.node_id: [] for node in plan.nodes}
    for dependency in plan.dependencies:
        prerequisites[dependency.node_id].append(dependency.depends_on)
    for node_id in list(prerequisites):
        prerequisites[node_id] = list(prerequisites[node_id])
    return prerequisites


def topological_order(plan: Plan) -> tuple:
    """Deterministic Kahn topological order; ties break by node ordinal then id."""
    _validate_shape(plan)
    prerequisites = build_prerequisites(plan)
    nodes = sorted(plan.nodes, key=lambda item: (item.ordinal, item.node_id))
    by_id = {node.node_id: node for node in nodes}
    blocked = {node.node_id: set(prerequisites[node.node_id]) for node in nodes}
    ordered: list = []
    while blocked:
        ready = [node_id for node_id in by_id if node_id in blocked and not blocked[node_id]]
        ready.sort(key=lambda node_id: (by_id[node_id].ordinal, node_id))
        if not ready:
            raise PlanValidationError("The plan dependency graph contains a cycle.")
        for node_id in ready:
            ordered.append(node_id)
            del blocked[node_id]
            for pending in blocked.values():
                pending.discard(node_id)
    return tuple(ordered)


def _validate_shape(plan: Plan) -> None:
    node_ids = [node.node_id for node in plan.nodes]
    if len(plan.nodes) == 0:
        raise PlanValidationError("A plan must contain at least one task node.")
    if len(plan.nodes) > plan.budgets.max_nodes or len(plan.nodes) > MAX_PLAN_NODES:
        raise PlanValidationError("The plan exceeds its node budget.")
    if len(set(node_ids)) != len(node_ids):
        raise PlanValidationError("Task node identifiers must be unique.")
    declared = set(node_ids)
    seen_edges = set()
    for dependency in plan.dependencies:
        if isinstance(dependency, bool) or not isinstance(dependency, Dependency):
            raise PlanValidationError("dependencies must contain Dependency values")
        if dependency.node_id not in declared or dependency.depends_on not in declared:
            raise PlanValidationError("A dependency references an unknown task node.")
        if dependency.plan_id != plan.plan_id:
            raise PlanValidationError("A dependency references a different plan.")
        if dependency.node_id == dependency.depends_on:
            raise PlanValidationError("A task cannot depend on itself.")
        edge = (dependency.node_id, dependency.depends_on)
        if edge in seen_edges:
            raise PlanValidationError("Duplicate dependency edges are rejected.")
        seen_edges.add(edge)
    for node in plan.nodes:
        if node.plan_id != plan.plan_id:
            raise PlanValidationError("A task node references a different plan.")


def validate_scopes_within_goal(plan: Plan, goal: Goal) -> None:
    """Reject plans whose requested data or tool scopes exceed the goal."""
    goal_data = {(scope.domain, scope.scope_type, scope.scope_id, scope.owner_id) for scope in goal.data_scopes}
    goal_tools = set(goal.tool_scopes)
    for node in plan.nodes:
        for scope in node.data_scopes:
            key = (scope.domain, scope.scope_type, scope.scope_id, scope.owner_id)
            if key not in goal_data:
                raise PlanValidationError(
                    "Task node " + node.node_id + " requests a data scope outside the goal scope."
                )
        for tool in node.tool_scopes:
            if tool not in goal_tools:
                raise PlanValidationError(
                    "Task node " + node.node_id + " requests a tool outside the goal tool scope."
                )


def validate_plan(plan: Plan, *, goal: Goal | None = None) -> None:
    """Full validation gate run before persistence or scheduling."""
    if isinstance(plan, bool) or not isinstance(plan, Plan):
        raise PlanValidationError("plan must be a Plan")
    if plan.status is not PlanStatus.DRAFT and goal is None:
        raise PlanValidationError("validation of a non-draft plan requires the goal for scope checks")
    _validate_shape(plan)
    topological_order(plan)
    if goal is not None:
        if plan.owner_id != goal.owner_id:
            raise PlanValidationError("The plan owner must match the goal owner.")
        validate_scopes_within_goal(plan, goal)
