"""SQLAlchemy records owned by the Agent Runtime.

Existing databases receive these tables through the ordered migration revision
0005_agent_runtime; fresh installs also receive them via metadata.create_all().
The current run state lives in agent_runs; checkpoint history stays separate
to preserve a resumable audit path.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)

from core.database import Base, utcnow_naive


class AgentDefinitionRecord(Base):
    __tablename__ = "agent_definitions"

    agent_id = Column(String(80), primary_key=True)
    version = Column(String(40), primary_key=True)
    goal = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    input_schema = Column(JSON, nullable=False, default=dict)
    output_schema = Column(JSON, nullable=False, default=dict)
    completion_kind = Column(String(60), nullable=False)
    completion_description = Column(Text, nullable=False)
    completion_min_results = Column(Integer, nullable=False, default=1)
    budget_max_iterations = Column(Integer, nullable=False, default=12)
    budget_deadline_seconds = Column(Integer, nullable=False, default=300)
    budget_max_tool_calls = Column(Integer, nullable=False, default=20)
    budget_max_model_tokens = Column(Integer, nullable=False, default=20000)
    budget_max_input_bytes = Column(Integer, nullable=False, default=65536)
    budget_max_output_bytes = Column(Integer, nullable=False, default=262144)
    allowed_tools = Column(JSON, nullable=False, default=list)
    allowed_models = Column(JSON, nullable=False, default=list)
    data_scopes = Column(JSON, nullable=False, default=list)
    approval_policy = Column(String(40), nullable=False, default="explicit")
    enabled = Column(Boolean, nullable=False, default=True)
    registered_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class AgentTaskRecord(Base):
    __tablename__ = "agent_tasks"

    task_id = Column(String(32), primary_key=True)
    agent_id = Column(String(80), nullable=False, index=True)
    agent_version = Column(String(40), nullable=False)
    owner_id = Column(String(160), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    data_scopes = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class AgentRunRecord(Base):
    """Current run state only; version is the optimistic concurrency token."""

    __tablename__ = "agent_runs"

    run_id = Column(String(32), primary_key=True)
    task_id = Column(String(32), nullable=False, index=True)
    agent_id = Column(String(80), nullable=False, index=True)
    agent_version = Column(String(40), nullable=False)
    owner_id = Column(String(160), nullable=False, index=True)
    trace_id = Column(String(80), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    scope_type = Column(String(40), nullable=False)
    scope_id = Column(String(160), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    attempt = Column(Integer, nullable=False, default=1)
    iteration = Column(Integer, nullable=False, default=0)
    tool_calls = Column(Integer, nullable=False, default=0)
    model_tokens = Column(Integer, nullable=False, default=0)
    last_checkpoint_sequence = Column(Integer, nullable=False, default=0)
    pending_approval_id = Column(String(80), nullable=True)
    stop_reason = Column(String(40), nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    outcome = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_task_status", "task_id", "status"),
    )


class AgentRunEventRecord(Base):
    """Append-only redacted run event; safe summaries only, never raw prompts."""

    __tablename__ = "agent_run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(32), nullable=False, unique=True, index=True)
    run_id = Column(
        String(32),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal = Column(Integer, nullable=False)
    event_type = Column(String(80), nullable=False, index=True)
    outcome = Column(String(40), nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)


class AgentCheckpointRecord(Base):
    """Checkpoint history kept separately from current agent_runs state."""

    __tablename__ = "agent_checkpoints"

    checkpoint_id = Column(String(32), primary_key=True)
    run_id = Column(
        String(32),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_checkpoint_run_sequence"),
    )
