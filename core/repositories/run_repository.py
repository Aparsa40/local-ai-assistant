"""Persistence adapters for agent runs, redacted run events, and checkpoints.

Optimistic concurrency: every run transition receives the expected persisted
version and writes version = expected + 1 only when it still matches. Conflicts
raise AgentConcurrencyError and the caller must reload state.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.agents.contracts import (
    AgentCheckpoint,
    AgentConcurrencyError,
    AgentRun,
    AgentRunStatus,
    RunEvent,
    StopReason,
    new_run_id,
)
from core.agents.models import (
    AgentCheckpointRecord,
    AgentRunEventRecord,
    AgentRunRecord,
)
from core.database import to_utc_naive
from .base import BaseRepository


def _aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _now() -> datetime:
    return datetime.now(timezone.utc)


_RUN_FIELDS = frozenset({
    "status", "iteration", "tool_calls", "model_tokens",
    "last_checkpoint_sequence", "pending_approval_id", "stop_reason",
    "error_code", "error_message", "outcome", "started_at", "updated_at",
    "finished_at",
})


class AgentRunRepository(BaseRepository):
    """Owns ORM access and transaction boundaries for the current run state."""

    @staticmethod
    def _to_contract(record: AgentRunRecord) -> AgentRun:
        return AgentRun(
            run_id=record.run_id,
            task_id=record.task_id,
            agent_id=record.agent_id,
            agent_version=record.agent_version,
            owner_id=record.owner_id,
            trace_id=record.trace_id,
            status=AgentRunStatus(record.status),
            scope_type=record.scope_type,
            scope_id=record.scope_id,
            version=int(record.version),
            attempt=int(record.attempt),
            iteration=int(record.iteration),
            tool_calls=int(record.tool_calls),
            model_tokens=int(record.model_tokens),
            last_checkpoint_sequence=int(record.last_checkpoint_sequence),
            pending_approval_id=record.pending_approval_id,
            stop_reason=StopReason(record.stop_reason) if record.stop_reason else None,
            error_code=record.error_code,
            error_message=record.error_message,
            outcome=dict(record.outcome) if record.outcome is not None else None,
            created_at=_aware(record.created_at),
            started_at=_aware(record.started_at),
            updated_at=_aware(record.updated_at),
            finished_at=_aware(record.finished_at),
        )

    def create(
        self,
        *,
        task_id: str,
        agent_id: str,
        agent_version: str,
        owner_id: str,
        trace_id: str,
        scope_type: str,
        scope_id: str,
    ) -> AgentRun:
        run = AgentRun(
            run_id=new_run_id(),
            task_id=task_id,
            agent_id=agent_id,
            agent_version=agent_version,
            owner_id=owner_id,
            trace_id=trace_id,
            status=AgentRunStatus.PENDING,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        record = AgentRunRecord(
            run_id=run.run_id,
            task_id=run.task_id,
            agent_id=run.agent_id,
            agent_version=run.agent_version,
            owner_id=run.owner_id,
            trace_id=run.trace_id,
            status=run.status.value,
            scope_type=run.scope_type,
            scope_id=run.scope_id,
            version=1,
            attempt=1,
            created_at=to_utc_naive(run.created_at),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def get(self, run_id: str) -> AgentRun | None:
        record = self.db.query(AgentRunRecord).filter(
            AgentRunRecord.run_id == run_id
        ).first()
        return self._to_contract(record) if record else None

    def list_recent(self, *, limit: int = 50) -> tuple:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records = (
            self.db.query(AgentRunRecord)
            .order_by(AgentRunRecord.created_at.desc(), AgentRunRecord.run_id)
            .limit(limit)
            .all()
        )
        return tuple(self._to_contract(record) for record in records)

    def list_by_status(self, *statuses, limit: int = 100) -> tuple:
        if not statuses or any(not isinstance(status, AgentRunStatus) for status in statuses):
            raise ValueError("at least one AgentRunStatus is required")
        records = (
            self.db.query(AgentRunRecord)
            .filter(AgentRunRecord.status.in_([item.value for item in statuses]))
            .order_by(AgentRunRecord.created_at.desc(), AgentRunRecord.run_id)
            .limit(limit)
            .all()
        )
        return tuple(self._to_contract(record) for record in records)

    def transition(self, run_id: str, *, expected_version: int, **updates) -> AgentRun | None:
        """Apply one optimistic-concurrency state transition.

        updates may set whitelisted current-state fields only. Run identity,
        task ownership, tracing, and version cannot be assigned here.
        """
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not updates or any(field not in _RUN_FIELDS for field in updates):
            raise ValueError("unsupported run field update")
        payload: dict = {}
        for field, value in updates.items():
            if field == "status":
                if not isinstance(value, AgentRunStatus):
                    raise ValueError("status must be an AgentRunStatus")
                payload["status"] = value.value
            elif field == "stop_reason":
                if value is not None and not isinstance(value, StopReason):
                    raise ValueError("stop_reason must be a StopReason or None")
                payload["stop_reason"] = value.value if value is not None else None
            elif field == "outcome":
                payload["outcome"] = dict(value) if value is not None else None
            elif field == "updated_at":
                payload["updated_at"] = to_utc_naive(value)
            elif field in {"started_at", "finished_at"}:
                payload[field] = to_utc_naive(value) if value is not None else None
            else:
                payload[field] = value
        if "updated_at" not in payload:
            payload["updated_at"] = to_utc_naive(_now())
        payload["version"] = expected_version + 1

        matched = (
            self.db.query(AgentRunRecord)
            .filter(
                AgentRunRecord.run_id == run_id,
                AgentRunRecord.version == expected_version,
            )
            .update(payload)
        )
        if not matched:
            raise AgentConcurrencyError(
                "Run state changed concurrently; reload the run before retrying."
            )
        self.db.commit()
        return self.get(run_id)

    def reset_stale_running(self, run_id: str, *, expected_version: int, error_code: str, error_message: str) -> AgentRun | None:
        """Recovery step for runs left RUNNING by an interrupted process.

        The stale run is moved to PAUSED with a truthful reason so eligible work
        can resume exactly once; execution state is not silently re-executed.
        """
        return self.transition(
            run_id,
            expected_version=expected_version,
            status=AgentRunStatus.PAUSED,
            stop_reason=StopReason.PAUSED_BY_REQUEST,
            error_code=error_code,
            error_message=error_message,
        )


class AgentRunEventRepository(BaseRepository):
    """Append-only persistence for redacted run events."""

    def append(self, event: RunEvent) -> RunEvent:
        record = AgentRunEventRecord(
            event_id=event.event_id,
            run_id=event.run_id,
            ordinal=int(event.ordinal),
            event_type=event.event_type,
            outcome=event.outcome,
            metadata_json=dict(event.metadata),
            created_at=to_utc_naive(event.created_at),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return event

    def list_for_run(self, run_id: str, *, limit: int = 200) -> tuple:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        records = (
            self.db.query(AgentRunEventRecord)
            .filter(AgentRunEventRecord.run_id == run_id)
            .order_by(AgentRunEventRecord.id)
            .limit(limit)
            .all()
        )
        return tuple(
            {
                "event_id": item.event_id,
                "run_id": item.run_id,
                "ordinal": item.ordinal,
                "event_type": item.event_type,
                "outcome": item.outcome,
                "metadata": dict(item.metadata_json or {}),
                "created_at": _aware(item.created_at),
            }
            for item in records
        )


class AgentCheckpointRepository(BaseRepository):
    """Append-only checkpoint history; current state lives on agent_runs."""

    def append(self, checkpoint: AgentCheckpoint) -> AgentCheckpoint:
        record = AgentCheckpointRecord(
            checkpoint_id=checkpoint.checkpoint_id,
            run_id=checkpoint.run_id,
            sequence=int(checkpoint.sequence),
            schema_version=int(checkpoint.schema_version),
            payload=dict(checkpoint.payload),
            created_at=to_utc_naive(checkpoint.created_at),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return checkpoint

    def latest(self, run_id: str) -> AgentCheckpoint | None:
        record = (
            self.db.query(AgentCheckpointRecord)
            .filter(AgentCheckpointRecord.run_id == run_id)
            .order_by(AgentCheckpointRecord.sequence.desc())
            .first()
        )
        if record is None:
            return None
        return AgentCheckpoint(
            checkpoint_id=record.checkpoint_id,
            run_id=record.run_id,
            sequence=int(record.sequence),
            schema_version=int(record.schema_version),
            payload=dict(record.payload or {}),
            created_at=_aware(record.created_at),
        )

    def list_for_run(self, run_id: str, *, limit: int = 100) -> tuple:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        records = (
            self.db.query(AgentCheckpointRecord)
            .filter(AgentCheckpointRecord.run_id == run_id)
            .order_by(AgentCheckpointRecord.sequence)
            .limit(limit)
            .all()
        )
        return tuple(
            AgentCheckpoint(
                checkpoint_id=record.checkpoint_id,
                run_id=record.run_id,
                sequence=int(record.sequence),
                schema_version=int(record.schema_version),
                payload=dict(record.payload or {}),
                created_at=_aware(record.created_at),
            )
            for record in records
        )
