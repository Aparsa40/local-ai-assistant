"""In-process operation registry for idempotency, replay and cancellation.

The registry is the uniqueness boundary for one request_id within one
conversation. Repeated submissions reconcile against the recorded operation
instead of creating duplicate turns or side effects. An SSE disconnect ends
only the subscriber stream; the leader keeps running and stays replayable.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional


class OperationState(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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

    @property
    def is_terminal(self) -> bool:
        return self.state is not OperationState.RUNNING

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

    def request_cancel(self) -> bool:
        """Record a cancellation request; returns False when already terminal."""
        if self.is_terminal:
            return False
        self.cancel_requested = True
        return True


class OperationRegistry:
    """Bounded in-memory registry; completed operations are retained for replay."""

    def __init__(self, *, max_completed: int = 200) -> None:
        self._operations: OrderedDict[tuple[int, str], ConversationOperation] = OrderedDict()
        self._max_completed = max_completed
        self._lock = asyncio.Lock()

    def start(self, session_id: int, request_id: str, user_message: str) -> tuple[ConversationOperation, bool]:
        """Atomically start or join the operation; created=False when joining."""
        key = (session_id, request_id)
        existing = self._operations.get(key)
        if existing is not None:
            return existing, False
        operation = ConversationOperation(
            request_id=request_id, session_id=session_id, user_message=user_message,
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
            # Never hold the condition lock while yielding to a network client;
            # a slow/disconnected subscriber must not block the lifecycle leader.
            for event in batch:
                yield event
                if event.type in {"final", "error", "cancelled"}:
                    return
