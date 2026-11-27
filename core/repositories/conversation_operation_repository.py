"""Durable persistence for Conversation Agent operation identities and events."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text


class ConversationOperationRepository:
    """Store idempotency identity and the safe lifecycle event log in SQLite."""

    def __init__(self, db) -> None:
        self._db = db

    def get(self, session_id: int, request_id: str) -> dict | None:
        row = self._db.execute(
            text(
                "SELECT session_id, request_id, message_hash, state, events, "
                "created_at, updated_at FROM conversation_operations "
                "WHERE session_id = :session_id AND request_id = :request_id"
            ),
            {"session_id": session_id, "request_id": request_id},
        ).mappings().first()
        if row is None:
            return None
        record = dict(row)
        events = record.get("events") or "[]"
        record["events"] = json.loads(events) if isinstance(events, str) else events
        return record

    def insert_if_absent(
        self,
        *,
        session_id: int,
        request_id: str,
        message_hash: str,
        state: str,
        events: list[dict],
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        result = self._db.execute(
            text(
                "INSERT OR IGNORE INTO conversation_operations "
                "(session_id, request_id, message_hash, state, events, created_at, updated_at) "
                "VALUES (:session_id, :request_id, :message_hash, :state, :events, :created_at, :updated_at)"
            ),
            {
                "session_id": session_id,
                "request_id": request_id,
                "message_hash": message_hash,
                "state": state,
                "events": json.dumps(events, ensure_ascii=False),
                "created_at": now,
                "updated_at": now,
            },
        )
        # Keep a bounded replay window while never pruning in-flight work.
        self._db.execute(
            text(
                "DELETE FROM conversation_operations WHERE rowid IN ("
                "SELECT rowid FROM conversation_operations WHERE state <> 'running' "
                "ORDER BY updated_at DESC LIMIT -1 OFFSET 2000)"
            )
        )
        self._db.commit()
        return result.rowcount == 1

    def save(self, *, session_id: int, request_id: str, state: str, events: list[dict]) -> None:
        self._db.execute(
            text(
                "UPDATE conversation_operations SET state = :state, events = :events, "
                "updated_at = :updated_at WHERE session_id = :session_id AND request_id = :request_id"
            ),
            {
                "session_id": session_id,
                "request_id": request_id,
                "state": state,
                "events": json.dumps(events, ensure_ascii=False),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._db.commit()
