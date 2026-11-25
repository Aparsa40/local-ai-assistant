"""Persistence adapters for Supervisor orchestration state.

Optimistic concurrency: every node transition receives the expected persisted
version and writes version = expected + 1 only when it still matches, mirroring
the AgentRunRepository contract. Plans, nodes, and dependencies are persisted
atomically; assignments, handoffs, and orchestration events are append-only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.agents.contracts import (
    CompletionCriteria,
    DataScope,
)
from core.database import to_utc_naive
from core.orchestration.contracts import (
    Assignment,
    Dependency,
    DependencyStatus,
    Evidence,
    Handoff,
    NodeStatus,
    OrchestrationBudgets,
    OrchestrationError,
    Plan,
    PlanStatus,
)
from core.orchestration.models import (
    OrchestrationAssignmentRecord,
    OrchestrationDependencyRecord,
    OrchestrationEventRecord,
    OrchestrationGoalRecord,
    OrchestrationHandoffRecord,
    OrchestrationNodeRecord,
    OrchestrationPlanRecord,
)
from .base import BaseRepository


def _aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scopes_to_json(scopes) -> list:
    return [
        {
            "domain": scope.domain,
            "scope_type": scope.scope_type,
            "scope_id": scope.scope_id,
            "owner_id": scope.owner_id,
        }
        for scope in scopes
    ]


def _scopes_from_json(items, default_owner: str) -> tuple:
    return tuple(
        DataScope(
            domain=item.get("domain", ""),
            scope_type=item.get("scope_type", ""),
            scope_id=item.get("scope_id", ""),
            owner_id=item.get("owner_id", default_owner),
        )
        for item in (items or [])
        if isinstance(item, dict)
    )


def _evidence_to_json(evidence) -> list:
    return [
        {
            "evidence_id": item.evidence_id,
            "kind": item.kind,
            "subject": item.subject,
            "claim": item.claim,
            "collected_at": item.collected_at.isoformat(),
        }
        for item in evidence
    ]


def _evidence_from_json(items) -> tuple:
    parsed = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        try:
            collected = item.get("collected_at")
            parsed.append(Evidence(
                evidence_id=item.get("evidence_id", ""),
                kind=item.get("kind", ""),
                subject=item.get("subject", ""),
                claim=item.get("claim", ""),
                collected_at=datetime.fromisoformat(collected) if isinstance(collected, str) else _now(),
            ))
        except Exception:
            continue
    return tuple(parsed)


def _completion_to_json(criteria) -> dict:
    return {
        "kind": criteria.kind,
        "description": criteria.description,
        "min_results": criteria.min_results,
    }


def _completion_from_json(payload):
    if not isinstance(payload, dict) or not payload.get("kind"):
        return None
    return CompletionCriteria(
        kind=str(payload.get("kind")),
        description=str(payload.get("description", "")),
        min_results=int(payload.get("min_results", 1)),
    )


def _budgets_to_json(budgets: OrchestrationBudgets) -> dict:
    return {
        "max_nodes": budgets.max_nodes,
        "max_wall_clock_seconds": budgets.max_wall_clock_seconds,
        "per_task_deadline_seconds": budgets.per_task_deadline_seconds,
        "max_retries_per_task": budgets.max_retries_per_task,
        "max_active_tasks": budgets.max_active_tasks,
    }


def _budgets_from_json(payload) -> OrchestrationBudgets:
    if not isinstance(payload, dict) or not payload:
        return OrchestrationBudgets()
    return OrchestrationBudgets(
        max_nodes=int(payload.get("max_nodes", 8)),
        max_wall_clock_seconds=int(payload.get("max_wall_clock_seconds", 1800)),
        per_task_deadline_seconds=int(payload.get("per_task_deadline_seconds", 300)),
        max_retries_per_task=int(payload.get("max_retries_per_task", 1)),
        max_active_tasks=int(payload.get("max_active_tasks", 1)),
    )


def new_event_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def new_handoff_size(payload: dict) -> int:
    import json

    return len(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8"))


NODE_FIELDS = frozenset({
    "status", "attempts", "agent_id", "agent_version", "run_id",
    "error_code", "error_message",
})

PLAN_FIELDS = frozenset({"status", "error_code", "error_message"})


class OrchestrationNodeRepository(BaseRepository):
    """Owns ORM access and transaction boundaries for orchestration nodes."""

    @staticmethod
    def _to_contract(record: OrchestrationNodeRecord, owner_id: str):
        from core.orchestration.contracts import TaskNode

        return TaskNode(
            node_id=record.node_id,
            plan_id=record.plan_id,
            ordinal=int(record.ordinal),
            title=record.title,
            required_capabilities=tuple(record.required_capabilities or ()),
            acceptance=(
                _completion_from_json(record.acceptance)
                or CompletionCriteria(kind="structured_result_present", description="Acceptance was recorded.")
            ),
            payload=dict(record.payload or {}),
            data_scopes=_scopes_from_json(record.data_scopes, owner_id),
            tool_scopes=tuple(record.tool_scopes or ()),
            status=NodeStatus(record.status),
            attempts=int(record.attempts),
            max_retries=int(record.max_retries),
            agent_id=record.agent_id,
            agent_version=record.agent_version,
            run_id=record.run_id,
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=_aware(record.created_at),
        )

    def create(self, node) -> object:
        record = OrchestrationNodeRecord(
            node_id=node.node_id,
            plan_id=node.plan_id,
            ordinal=int(node.ordinal),
            title=node.title,
            required_capabilities=list(node.required_capabilities),
            acceptance=_completion_to_json(node.acceptance),
            payload=dict(node.payload),
            data_scopes=_scopes_to_json(node.data_scopes),
            tool_scopes=list(node.tool_scopes),
            status=node.status.value,
            attempts=int(node.attempts),
            max_retries=int(node.max_retries),
            agent_id=node.agent_id,
            agent_version=node.agent_version,
            run_id=node.run_id,
            error_code=node.error_code,
            error_message=node.error_message,
            created_at=to_utc_naive(node.created_at),
        )
        self.db.add(record)
        return record

    def get(self, node_id: str, owner_id: str):
        record = self.db.query(OrchestrationNodeRecord).filter(
            OrchestrationNodeRecord.node_id == node_id
        ).first()
        return self._to_contract(record, owner_id) if record else None

    def list_for_plan(self, plan_id: str, owner_id: str) -> tuple:
        records = (
            self.db.query(OrchestrationNodeRecord)
            .filter(OrchestrationNodeRecord.plan_id == plan_id)
            .order_by(OrchestrationNodeRecord.ordinal, OrchestrationNodeRecord.node_id)
            .all()
        )
        return tuple(self._to_contract(record, owner_id) for record in records)

    def transition(self, node_id: str, *, expected_version: int, **updates):
        """Apply one optimistic-concurrency node state transition."""
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not updates or any(field not in NODE_FIELDS for field in updates):
            raise ValueError("unsupported node field update")
        payload: dict = {}
        for field, value in updates.items():
            if field == "status":
                if not isinstance(value, NodeStatus):
                    raise ValueError("status must be a NodeStatus")
                payload["status"] = value.value
            elif field == "attempts":
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("attempts must be a non-negative integer")
                payload["attempts"] = value
            else:
                if value is not None and (not isinstance(value, str) or len(value) > 300):
                    raise ValueError(field + " is invalid or too long")
                payload[field] = value
        payload["updated_at"] = to_utc_naive(_now())
        payload["version"] = expected_version + 1
        matched = (
            self.db.query(OrchestrationNodeRecord)
            .filter(
                OrchestrationNodeRecord.node_id == node_id,
                OrchestrationNodeRecord.version == expected_version,
            )
            .update(payload)
        )
        if not matched:
            from core.agents.contracts import AgentConcurrencyError

            raise AgentConcurrencyError(
                "Node state changed concurrently; reload the plan before retrying."
            )
        self.db.commit()
        record = self.db.query(OrchestrationNodeRecord).filter(
            OrchestrationNodeRecord.node_id == node_id
        ).first()
        plan = self.db.query(OrchestrationPlanRecord).filter(
            OrchestrationPlanRecord.plan_id == record.plan_id
        ).first() if record else None
        return self._to_contract(record, plan.owner_id if plan else "") if record else None

    def list_by_status(self, *statuses, limit: int = 100) -> tuple:
        if not statuses or any(not isinstance(status, NodeStatus) for status in statuses):
            raise ValueError("at least one NodeStatus is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records = (
            self.db.query(OrchestrationNodeRecord)
            .filter(OrchestrationNodeRecord.status.in_([item.value for item in statuses]))
            .order_by(OrchestrationNodeRecord.created_at, OrchestrationNodeRecord.node_id)
            .limit(limit)
            .all()
        )
        owner_ids = {
            plan.plan_id: plan.owner_id
            for plan in self.db.query(OrchestrationPlanRecord).filter(
                OrchestrationPlanRecord.plan_id.in_([record.plan_id for record in records])
            ).all()
        }
        return tuple(
            self._to_contract(record, owner_ids.get(record.plan_id, "")) for record in records
        )


class OrchestrationPlanRepository(BaseRepository):
    """Owns plan persistence with atomic plan/node/dependency creation."""

    def __init__(self, db, *, nodes: OrchestrationNodeRepository | None = None) -> None:
        super().__init__(db)
        self._nodes = nodes if nodes is not None else OrchestrationNodeRepository(db)

    @staticmethod
    def _to_contract(record: OrchestrationPlanRecord, nodes: tuple, dependencies: tuple) -> Plan:
        return Plan(
            plan_id=record.plan_id,
            goal_id=record.goal_id,
            parent_run_id=record.parent_run_id,
            parent_task_id=record.parent_task_id,
            owner_id=record.owner_id,
            revision=int(record.revision),
            status=PlanStatus(record.status),
            nodes=nodes,
            dependencies=dependencies,
            budgets=_budgets_from_json(record.budgets),
            acceptance=_completion_from_json(record.acceptance),
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=_aware(record.created_at),
        )

    def create(self, plan: Plan) -> Plan:
        if not isinstance(plan, Plan):
            raise OrchestrationError("plan must be a Plan")
        record = OrchestrationPlanRecord(
            plan_id=plan.plan_id,
            goal_id=plan.goal_id,
            parent_run_id=plan.parent_run_id,
            parent_task_id=plan.parent_task_id,
            owner_id=plan.owner_id,
            revision=int(plan.revision),
            status=plan.status.value,
            budgets=_budgets_to_json(plan.budgets),
            acceptance=_completion_to_json(plan.acceptance) if plan.acceptance else None,
            error_code=plan.error_code,
            error_message=plan.error_message,
            created_at=to_utc_naive(plan.created_at),
        )
        self.db.add(record)
        for node in plan.nodes:
            self._nodes.create(node)
        for dependency in plan.dependencies:
            self.db.add(OrchestrationDependencyRecord(
                dependency_id=dependency.dependency_id,
                plan_id=dependency.plan_id,
                node_id=dependency.node_id,
                depends_on=dependency.depends_on,
                policy=dependency.policy,
                status=dependency.status.value,
                created_at=to_utc_naive(dependency.created_at),
            ))
        self.db.commit()
        return self.get(plan.plan_id)

    def _load_dependencies(self, plan_id: str) -> tuple:
        records = (
            self.db.query(OrchestrationDependencyRecord)
            .filter(OrchestrationDependencyRecord.plan_id == plan_id)
            .order_by(OrchestrationDependencyRecord.created_at, OrchestrationDependencyRecord.dependency_id)
            .all()
        )
        return tuple(
            Dependency(
                dependency_id=record.dependency_id,
                plan_id=record.plan_id,
                node_id=record.node_id,
                depends_on=record.depends_on,
                policy=record.policy,
                status=DependencyStatus(record.status),
                created_at=_aware(record.created_at),
            )
            for record in records
        )

    def get(self, plan_id: str) -> Plan | None:
        record = self.db.query(OrchestrationPlanRecord).filter(
            OrchestrationPlanRecord.plan_id == plan_id
        ).first()
        if record is None:
            return None
        nodes = self._nodes.list_for_plan(plan_id, record.owner_id)
        return self._to_contract(record, nodes, self._load_dependencies(plan_id))

    def list_recent(self, *, limit: int = 50) -> tuple:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records = (
            self.db.query(OrchestrationPlanRecord)
            .order_by(OrchestrationPlanRecord.created_at.desc(), OrchestrationPlanRecord.plan_id)
            .limit(limit)
            .all()
        )
        return tuple(self.get(record.plan_id) for record in records)

    def list_by_parent_run(self, parent_run_id: str) -> Plan | None:
        record = self.db.query(OrchestrationPlanRecord).filter(
            OrchestrationPlanRecord.parent_run_id == parent_run_id
        ).first()
        return self.get(record.plan_id) if record else None

    def transition(self, plan_id: str, *, expected_version: int, **updates) -> Plan | None:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not updates or any(field not in PLAN_FIELDS for field in updates):
            raise ValueError("unsupported plan field update")
        payload: dict = {}
        for field, value in updates.items():
            if field == "status":
                if not isinstance(value, PlanStatus):
                    raise ValueError("status must be a PlanStatus")
                payload["status"] = value.value
            else:
                if value is not None and (not isinstance(value, str) or len(value) > 300):
                    raise ValueError(field + " is invalid or too long")
                payload[field] = value
        payload["updated_at"] = to_utc_naive(_now())
        payload["version"] = expected_version + 1
        matched = (
            self.db.query(OrchestrationPlanRecord)
            .filter(
                OrchestrationPlanRecord.plan_id == plan_id,
                OrchestrationPlanRecord.version == expected_version,
            )
            .update(payload)
        )
        if not matched:
            from core.agents.contracts import AgentConcurrencyError

            raise AgentConcurrencyError(
                "Plan state changed concurrently; reload the plan before retrying."
            )
        self.db.commit()
        return self.get(plan_id)

    def set_dependency_status(self, dependency_id: str, status: DependencyStatus) -> None:
        if not isinstance(status, DependencyStatus):
            raise ValueError("status must be a DependencyStatus")
        record = self.db.query(OrchestrationDependencyRecord).filter(
            OrchestrationDependencyRecord.dependency_id == dependency_id
        ).first()
        if record is None:
            raise OrchestrationError("Dependency was not found.")
        record.status = status.value
        self.db.commit()


class OrchestrationAssignmentRepository(BaseRepository):
    """Append-only assignment decision history."""

    def append(self, assignment: Assignment) -> Assignment:
        self.db.add(OrchestrationAssignmentRecord(
            assignment_id=assignment.assignment_id,
            plan_id=assignment.plan_id,
            node_id=assignment.node_id,
            decision=assignment.decision,
            agent_id=assignment.agent_id,
            agent_version=assignment.agent_version,
            run_id=assignment.run_id,
            reasons=list(assignment.reasons),
            evidence=_evidence_to_json(assignment.evidence),
            created_at=to_utc_naive(assignment.decided_at),
        ))
        self.db.commit()
        return assignment

    def list_for_plan(self, plan_id: str, *, limit: int = 100) -> tuple:
        records = (
            self.db.query(OrchestrationAssignmentRecord)
            .filter(OrchestrationAssignmentRecord.plan_id == plan_id)
            .order_by(OrchestrationAssignmentRecord.created_at, OrchestrationAssignmentRecord.assignment_id)
            .limit(limit)
            .all()
        )
        return tuple(
            {
                "assignment_id": record.assignment_id,
                "node_id": record.node_id,
                "decision": record.decision,
                "agent_id": record.agent_id,
                "agent_version": record.agent_version,
                "run_id": record.run_id,
                "reasons": list(record.reasons or []),
                "evidence": list(record.evidence or []),
            }
            for record in records
        )


class OrchestrationHandoffRepository(BaseRepository):
    """Append-only versioned handoff envelopes."""

    def append(self, handoff: Handoff) -> Handoff:
        self.db.add(OrchestrationHandoffRecord(
            handoff_id=handoff.handoff_id,
            plan_id=handoff.plan_id,
            node_id=handoff.node_id,
            from_run_id=handoff.from_run_id,
            envelope_version=handoff.envelope_version,
            payload=dict(handoff.payload),
            status=handoff.status,
            evidence=_evidence_to_json(handoff.evidence),
            size_bytes=new_handoff_size(handoff.payload),
            created_at=to_utc_naive(handoff.created_at),
        ))
        self.db.commit()
        return handoff

    def list_for_plan(self, plan_id: str, *, limit: int = 200) -> tuple:
        records = (
            self.db.query(OrchestrationHandoffRecord)
            .filter(OrchestrationHandoffRecord.plan_id == plan_id)
            .order_by(OrchestrationHandoffRecord.created_at, OrchestrationHandoffRecord.handoff_id)
            .limit(limit)
            .all()
        )
        return tuple(
            Handoff(
                handoff_id=record.handoff_id,
                plan_id=record.plan_id,
                node_id=record.node_id,
                from_run_id=record.from_run_id,
                envelope_version=record.envelope_version,
                payload=dict(record.payload or {}),
                status=record.status,
                evidence=_evidence_from_json(record.evidence),
                created_at=_aware(record.created_at),
            )
            for record in records
        )


class OrchestrationEventRepository(BaseRepository):
    """Append-only redacted orchestration event stream."""

    def record(self, *, plan_id: str, node_id: str | None, event_type: str,
               outcome: str, metadata: dict | None = None) -> None:
        import json

        from core.agents.contracts import _required_text

        encoded = json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 4096:
            raise OrchestrationError("orchestration event metadata exceeds the size limit")
        self.db.add(OrchestrationEventRecord(
            event_id=new_event_id(),
            plan_id=plan_id,
            node_id=node_id,
            event_type=_required_text(event_type, "event_type", maximum=80),
            outcome=_required_text(outcome, "event outcome", maximum=40),
            metadata_json=dict(metadata or {}),
            created_at=to_utc_naive(_now()),
        ))
        self.db.commit()

    def list_for_plan(self, plan_id: str, *, limit: int = 200) -> tuple:
        records = (
            self.db.query(OrchestrationEventRecord)
            .filter(OrchestrationEventRecord.plan_id == plan_id)
            .order_by(OrchestrationEventRecord.id)
            .limit(limit)
            .all()
        )
        return tuple(
            {
                "event_id": record.event_id,
                "plan_id": record.plan_id,
                "node_id": record.node_id,
                "event_type": record.event_type,
                "outcome": record.outcome,
                "metadata": dict(record.metadata_json or {}),
                "created_at": _aware(record.created_at),
            }
            for record in records
        )

    def list_by_type(self, event_type: str, *, limit: int = 100) -> tuple:
        records = (
            self.db.query(OrchestrationEventRecord)
            .filter(OrchestrationEventRecord.event_type == event_type)
            .order_by(OrchestrationEventRecord.id)
            .limit(limit)
            .all()
        )
        return tuple(
            {
                "event_id": record.event_id,
                "plan_id": record.plan_id,
                "node_id": record.node_id,
                "event_type": record.event_type,
                "outcome": record.outcome,
                "metadata": dict(record.metadata_json or {}),
                "created_at": _aware(record.created_at),
            }
            for record in records
        )


class OrchestrationGoalRepository(BaseRepository):
    """Persistence adapter for orchestration goals."""

    @staticmethod
    def _to_contract(record: OrchestrationGoalRecord):
        from core.orchestration.contracts import Goal, OrchestrationBudgets

        budgets = _budgets_from_json(record.budgets)
        return Goal(
            goal_id=record.goal_id,
            owner_id=record.owner_id,
            description=record.description,
            success_criteria=record.success_criteria,
            data_scopes=_scopes_from_json(record.data_scopes, record.owner_id),
            tool_scopes=tuple(record.tool_scopes or ()),
            budgets=budgets if isinstance(budgets, OrchestrationBudgets) else OrchestrationBudgets(),
            created_at=_aware(record.created_at),
        )

    def create(self, goal) -> object:
        from core.orchestration.contracts import Goal

        if not isinstance(goal, Goal):
            raise OrchestrationError("goal must be a Goal")
        record = OrchestrationGoalRecord(
            goal_id=goal.goal_id,
            owner_id=goal.owner_id,
            description=goal.description,
            success_criteria=goal.success_criteria,
            data_scopes=_scopes_to_json(goal.data_scopes),
            tool_scopes=list(goal.tool_scopes),
            budgets=_budgets_to_json(goal.budgets),
            status="open",
            created_at=to_utc_naive(goal.created_at),
        )
        self.db.add(record)
        self.db.commit()
        return self.get(goal.goal_id)

    def get(self, goal_id: str):
        record = self.db.query(OrchestrationGoalRecord).filter(
            OrchestrationGoalRecord.goal_id == goal_id
        ).first()
        return self._to_contract(record) if record else None
