"""Deterministic result aggregation for finished plans (WP-7.5).

Aggregation follows explicit acceptance criteria: a node contributes its
recorded outcome and evidence; contradictions and incomplete evidence are
surfaced rather than resolved by majority vote or stylistic similarity.
"""
from __future__ import annotations

from core.orchestration.contracts import (
    AggregateResult,
    NodeStatus,
)


class ResultAggregator:
    """Builds the plan-level aggregate outcome from persisted node states."""

    def __init__(self, handoffs_repository, *, events=None) -> None:
        self.handoffs = handoffs_repository
        self.events = events

    def aggregate(self, plan) -> AggregateResult:
        node_states = {node.node_id: node for node in plan.nodes}
        handoff_by_node: dict = {}
        for handoff in self.handoffs.list_for_plan(plan.plan_id, limit=100):
            handoff_by_node.setdefault(handoff.node_id, handoff)

        outcomes: list = []
        conflicts: list = []
        missing_evidence: list = []

        for node in sorted(plan.nodes, key=lambda item: (item.ordinal, item.node_id)):
            entry = {
                "node_id": node.node_id,
                "title": node.title,
                "status": node.status.value,
                "run_id": node.run_id,
                "attempt": node.attempts,
            }
            handoff = handoff_by_node.get(node.node_id)
            if handoff is not None:
                entry["handoff_id"] = handoff.handoff_id
                entry["handoff_status"] = handoff.status
                entry["summary"] = str(handoff.payload.get("summary", ""))[:300]
                entry["evidence_count"] = len(handoff.evidence)
                if handoff.status != "complete":
                    missing_evidence.append(
                        "Node " + node.node_id + " recorded a handoff with "
                        + handoff.status + " evidence."
                    )
            elif node.status is NodeStatus.COMPLETED:
                missing_evidence.append(
                    "Node " + node.node_id + " completed without a recorded handoff."
                )
            if node.status is NodeStatus.FAILED and node.error_code:
                conflicts.append(
                    "Node " + node.node_id + " failed: " + str(node.error_code)
                )
            elif node.status is NodeStatus.SKIPPED:
                conflicts.append(
                    "Node " + node.node_id + " was skipped: " + str(node.error_code or "prerequisite_unsatisfied")
                )
            outcomes.append(entry)

        completed = sum(1 for entry in outcomes if entry["status"] == "completed")
        failed = sum(1 for entry in outcomes if entry["status"] == "failed")
        cancelled = sum(1 for entry in outcomes if entry["status"] == "cancelled")

        if cancelled and completed == 0:
            status = "cancelled"
        elif failed:
            status = "failed" if completed == 0 else "partial"
        elif completed == 0:
            status = "failed"
        elif missing_evidence:
            status = "partial"
        else:
            status = "completed"

        aggregate = AggregateResult(
            plan_id=plan.plan_id,
            parent_run_id=plan.parent_run_id,
            status=status,
            outcomes=tuple(outcomes),
            conflicts=tuple(conflicts),
            missing_evidence=tuple(missing_evidence),
        )
        if self.events is not None:
            try:
                self.events.record(
                    plan_id=plan.plan_id,
                    node_id=None,
                    event_type="plan_aggregated",
                    outcome=status,
                    metadata={
                        "completed": completed,
                        "failed": failed,
                        "cancelled": cancelled,
                        "conflicts": len(conflicts),
                        "missing_evidence": len(missing_evidence),
                    },
                )
            except Exception:
                # Aggregation itself already exposes the state; event loss must
                # not mask the aggregate answer.
                pass
        return aggregate
