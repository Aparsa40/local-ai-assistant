"""Durable operation registry for idempotency, replay and cancellation."""
from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncIterator, Callable, Optional

from core.conversation_agent.contracts import ConversationEvent


class OperationState(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _message_hash(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _event_to_record(event: ConversationEvent) -> dict:
    return {
        "event_id": event.event_id,
        "request_id": event.request_id,
        "conversation_id": event.conversation_id,
        "type": event.type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


def _event_from_record(record: dict) -> ConversationEvent:
    created_at = record.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return ConversationEvent(
        event_id=record["event_id"],
        request_id=record["request_id"],
        conversation_id=int(record["conversation_id"]),
        type=record["type"],
        payload=dict(record.get("payload") or {}),
        created_at=created_at or datetime.now(timezone.utc),
    )


@dataclass
class ConversationOperation:
    request_id: str
    session_id: int
    user_message: str
    state: OperationState = OperationState.RUNNING
    events: list[ConversationEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    terminal: Optional[ConversationEvent] = None
    cancel_requested: bool = False
    leader_task: Optional[asyncio.Task] = None
    message_hash: str = ""
    persist_callback: Callable[["ConversationOperation"], None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.message_hash:
            self.message_hash = _message_hash(self.user_message)

    @property
    def is_terminal(self) -> bool:
        return self.state is not OperationState.RUNNING

    def matches_message(self, message: str) -> bool:
        return self.message_hash == _message_hash(message)

    async def publish(self, event: ConversationEvent) -> None:
        async with self.condition:
            self.events.append(event)
            if event.type in {"final", "error", "cancelled"}:
                self.terminal = event
                self.state = {
                    "final": OperationState.COMPLETED,
                    "error": OperationState.FAILED,
                    "cancelled": OperationState.CANCELLED,
                }[event.type]
            self.condition.notify_all()
        if self.persist_callback is not None:
            self.persist_callback(self)

    def request_cancel(self) -> bool:
        """Record a cancellation request; returns False when already terminal."""
        if self.is_terminal:
            return False
        self.cancel_requested = True
        return True


class OperationRegistry:
    """Bounded in-memory follower registry backed by durable SQLite operation rows."""

    def __init__(self, *, max_completed: int = 200, session_factory=None) -> None:
        self._operations: OrderedDict[tuple[int, str], ConversationOperation] = OrderedDict()
        self._max_completed = max_completed
        self._session_factory = session_factory

    def _repository(self, db):
        from core.repositories.conversation_operation_repository import ConversationOperationRepository
        return ConversationOperationRepository(db)

    def _persist(self, operation: ConversationOperation) -> None:
        if self._session_factory is None:
            return
        with self._session_factory() as db:
            self._repository(db).save(
                session_id=operation.session_id,
                request_id=operation.request_id,
                state=operation.state.value,
                events=[_event_to_record(event) for event in operation.events],
            )

    def _restore(self, record: dict) -> ConversationOperation:
        operation = ConversationOperation(
            request_id=record["request_id"],
            session_id=int(record["session_id"]),
            user_message="",
            state=OperationState(record["state"]),
            events=[_event_from_record(item) for item in record.get("events", [])],
            message_hash=record["message_hash"],
            persist_callback=self._persist,
        )
        terminal = next(
            (event for event in reversed(operation.events) if event.type in {"final", "error", "cancelled"}),
            None,
        )
        operation.terminal = terminal
        if terminal is not None:
            operation.state = {
                "final": OperationState.COMPLETED,
                "error": OperationState.FAILED,
                "cancelled": OperationState.CANCELLED,
            }[terminal.type]
        return operation

    def start(self, session_id: int, request_id: str, user_message: str) -> tuple[ConversationOperation, bool]:
        """Atomically start or reconcile one operation per conversation/request ID."""
        key = (session_id, request_id)
        existing = self._operations.get(key)
        if existing is not None:
            return existing, False

        if self._session_factory is not None:
            with self._session_factory() as db:
                repository = self._repository(db)
                record = repository.get(session_id, request_id)
                if record is not None:
                    operation = self._restore(record)
                    if operation.state is OperationState.RUNNING:
                        # A prior process stopped before recording a terminal result.
                        # Never rerun automatically: the provider/side-effect outcome
                        # may be uncertain. Persist a terminal reconciliation event.
                        interrupted = ConversationEvent(
                            event_id="evt_recovered_" + hashlib.sha256(request_id.encode()).hexdigest()[:16],
                            request_id=request_id,
                            conversation_id=session_id,
                            type="error",
                            payload={
                                "error_code": "operation_interrupted",
                                "message": "The previous server process stopped before this request reached a terminal state. Submit a new request after reviewing its status.",
                            },
                        )
                        operation.events.append(interrupted)
                        operation.terminal = interrupted
                        operation.state = OperationState.FAILED
                        repository.save(
                            session_id=session_id,
                            request_id=request_id,
                            state=operation.state.value,
                            events=[_event_to_record(event) for event in operation.events],
                        )
                    self._operations[key] = operation
                    return operation, False

            operation = ConversationOperation(
                request_id=request_id,
                session_id=session_id,
                user_message=user_message,
                persist_callback=self._persist,
            )
            with self._session_factory() as db:
                inserted = self._repository(db).insert_if_absent(
                    session_id=session_id,
                    request_id=request_id,
                    message_hash=operation.message_hash,
                    state=operation.state.value,
                    events=[],
                )
            if not inserted:
                # Another worker won the uniqueness race; reconcile from storage.
                return self.start(session_id, request_id, user_message)
        else:
            operation = ConversationOperation(
                request_id=request_id,
                session_id=session_id,
                user_message=user_message,
            )

        self._operations[key] = operation
        self._evict()
        return operation, True

    def get(self, session_id: int, request_id: str) -> ConversationOperation | None:
        return self._operations.get((session_id, request_id))

    def request_cancel(self, session_id: int, request_id: str) -> bool:
        operation = self.get(session_id, request_id)
        if operation is None:
            return False
        return operation.request_cancel()

    def _evict(self) -> None:
        completions = [key for key, op in self._operations.items() if op.is_terminal]
        while len(completions) > self._max_completed:
            oldest = completions.pop(0)
            self._operations.pop(oldest, None)
        while len(self._operations) > self._max_completed * 2:
            running = [key for key, op in self._operations.items() if not op.is_terminal]
            for key in list(self._operations):
                if key in running:
                    continue
                self._operations.pop(key)
                break
            else:
                break

    async def follow(self, operation: ConversationOperation, *, from_index: int = 0) -> AsyncIterator[ConversationEvent]:
        """Replay buffered events, then follow live events until terminal."""
        index = from_index
        while True:
            async with operation.condition:
                while index >= len(operation.events):
                    if operation.is_terminal:
                        return
                    await operation.condition.wait()
                batch = list(operation.events[index:])
                index = len(operation.events)
            # Never hold the condition lock while yielding to a network client.
            for event in batch:
                yield event
                if event.type in {"final", "error", "cancelled"}:
                    return
