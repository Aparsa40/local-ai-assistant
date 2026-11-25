"""SQLAlchemy records owned by the Phase 7 Supervisor orchestration layer.

Existing databases receive these tables through the ordered migration revision
0006_orchestration; fresh installs also receive them via metadata.create_all().
Plan structure lives in orchestration_plans; per-node current state lives in
orchestration_nodes with an optimistic concurrency token; handoffs,
assignments, and events are append-only.
"""
from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)

from core.database import Base, utcnow_naive


class OrchestrationGoalRecord(Base):
    __tablename__ = "orchestration_goals"

    goal_id = Column(String(32), primary_key=True)
    owner_id = Column(String(160), nullable=False, index=True)
    description = Column(Text, nullable=False)
    success_criteria = Column(Text, nullable=False)
    data_scopes = Column(JSON, nullable=False, default=list)
    tool_scopes = Column(JSON, nullable=False, default=list)
    budgets = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class OrchestrationPlanRecord(Base):
    __tablename__ = "orchestration_plans"

    plan_id = Column(String(32), primary_key=True)
    goal_id = Column(String(32), nullable=False, index=True)
    parent_run_id = Column(String(32), nullable=False, index=True)
    parent_task_id = Column(String(32), nullable=False)
    owner_id = Column(String(160), nullable=False, index=True)
    revision = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="draft", index=True)
    budgets = Column(JSON, nullable=False, default=dict)
    acceptance = Column(JSON, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class OrchestrationNodeRecord(Base):
    """Current node state only; version is the optimistic concurrency token."""

    __tablename__ = "orchestration_nodes"

    node_id = Column(String(32), primary_key=True)
    plan_id = Column(
        String(32),
        ForeignKey("orchestration_plans.plan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal = Column(Integer, nullable=False, default=0)
    title = Column(String(200), nullable=False)
    required_capabilities = Column(JSON, nullable=False, default=list)
    acceptance = Column(JSON, nullable=False, default=dict)
    payload = Column(JSON, nullable=False, default=dict)
    data_scopes = Column(JSON, nullable=False, default=list)
    tool_scopes = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=0)
    agent_id = Column(String(80), nullable=True)
    agent_version = Column(String(40), nullable=True)
    run_id = Column(String(32), nullable=True, index=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class OrchestrationDependencyRecord(Base):
    __tablename__ = "orchestration_dependencies"

    dependency_id = Column(String(32), primary_key=True)
    plan_id = Column(
        String(32),
        ForeignKey("orchestration_plans.plan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(32), nullable=False, index=True)
    depends_on = Column(String(32), nullable=False, index=True)
    policy = Column(String(40), nullable=False, default="all_success")
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class OrchestrationAssignmentRecord(Base):
    """Append-only assignment decision history with explainable evidence."""

    __tablename__ = "orchestration_assignments"

    assignment_id = Column(String(32), primary_key=True)
    plan_id = Column(
        String(32),
        ForeignKey("orchestration_plans.plan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(32), nullable=False, index=True)
    decision = Column(String(20), nullable=False)
    agent_id = Column(String(80), nullable=True)
    agent_version = Column(String(40), nullable=True)
    run_id = Column(String(32), nullable=True)
    reasons = Column(JSON, nullable=False, default=list)
    evidence = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class OrchestrationHandoffRecord(Base):
    """Append-only versioned handoff envelopes with provenance."""

    __tablename__ = "orchestration_handoffs"

    handoff_id = Column(String(32), primary_key=True)
    plan_id = Column(
        String(32),
        ForeignKey("orchestration_plans.plan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(32), nullable=False, index=True)
    from_run_id = Column(String(32), nullable=False, index=True)
    envelope_version = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="complete")
    evidence = Column(JSON, nullable=False, default=list)
    size_bytes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class OrchestrationEventRecord(Base):
    """Append-only redacted orchestration event; safe summaries only."""

    __tablename__ = "orchestration_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(32), nullable=False, unique=True, index=True)
    plan_id = Column(
        String(32),
        ForeignKey("orchestration_plans.plan_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(32), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    outcome = Column(String(40), nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
