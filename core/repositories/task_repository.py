"""Persistence adapter for agent tasks with explicit ownership scopes."""
from __future__ import annotations

from datetime import timezone

from core.agents.contracts import AgentTask, DataScope, TaskStatus, new_task_id
from core.agents.models import AgentTaskRecord
from core.database import to_utc_naive
from .base import BaseRepository


class AgentTaskRepository(BaseRepository):
    """Owns ORM access and transaction boundaries for agent tasks."""

    @staticmethod
    def _aware(value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @classmethod
    def _to_contract(cls, record: AgentTaskRecord) -> AgentTask:
        return AgentTask(
            task_id=record.task_id,
            agent_id=record.agent_id,
            agent_version=record.agent_version,
            owner_id=record.owner_id,
            title=record.title,
            payload=dict(record.payload or {}),
            data_scopes=tuple(
                DataScope(
                    domain=item.get("domain", ""),
                    scope_type=item.get("scope_type", ""),
                    scope_id=item.get("scope_id", ""),
                    owner_id=item.get("owner_id", record.owner_id),
                )
                for item in (record.data_scopes or [])
                if isinstance(item, dict)
            ),
            status=TaskStatus(record.status),
            created_at=cls._aware(record.created_at),
        )

    def create(
        self,
        *,
        agent_id: str,
        agent_version: str,
        owner_id: str,
        title: str,
        payload: dict,
        data_scopes: tuple = (),
    ) -> AgentTask:
        task = AgentTask(
            task_id=new_task_id(),
            agent_id=agent_id,
            agent_version=agent_version,
            owner_id=owner_id,
            title=title,
            payload=payload,
            data_scopes=data_scopes,
        )
        record = AgentTaskRecord(
            task_id=task.task_id,
            agent_id=task.agent_id,
            agent_version=task.agent_version,
            owner_id=task.owner_id,
            title=task.title,
            payload=task.payload,
            data_scopes=[
                {
                    "domain": scope.domain,
                    "scope_type": scope.scope_type,
                    "scope_id": scope.scope_id,
                    "owner_id": scope.owner_id,
                }
                for scope in task.data_scopes
            ],
            status=task.status.value,
            created_at=to_utc_naive(task.created_at),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def get(self, task_id: str) -> AgentTask | None:
        record = self.db.query(AgentTaskRecord).filter(
            AgentTaskRecord.task_id == task_id
        ).first()
        return self._to_contract(record) if record else None

    def update_status(self, task_id: str, status: TaskStatus) -> AgentTask | None:
        if not isinstance(status, TaskStatus):
            raise ValueError("status must be a TaskStatus")
        record = self.db.query(AgentTaskRecord).filter(
            AgentTaskRecord.task_id == task_id
        ).first()
        if record is None:
            return None
        record.status = status.value
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def update_payload(self, task_id: str, payload: dict) -> AgentTask | None:
        """Bound and record one payload update for an existing task."""
        import json

        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-serializable") from exc
        if len(encoded.encode("utf-8")) > 32768:
            raise ValueError("payload exceeds the maximum size")
        record = self.db.query(AgentTaskRecord).filter(
            AgentTaskRecord.task_id == task_id
        ).first()
        if record is None:
            return None
        # Re-validate through the contract before persisting.
        AgentTask(
            task_id=record.task_id,
            agent_id=record.agent_id,
            agent_version=record.agent_version,
            owner_id=record.owner_id,
            title=record.title,
            payload=payload,
            data_scopes=self._to_contract(record).data_scopes,
            status=TaskStatus(record.status),
            created_at=self._aware(record.created_at),
        )
        record.payload = payload
        self.db.commit()
        self.db.refresh(record)
        return self._to_contract(record)

    def list_recent(self, *, limit: int = 50) -> tuple:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records = (
            self.db.query(AgentTaskRecord)
            .order_by(AgentTaskRecord.created_at.desc(), AgentTaskRecord.task_id)
            .limit(limit)
            .all()
        )
        return tuple(self._to_contract(record) for record in records)
