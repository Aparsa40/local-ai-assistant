"""Persistence and restart-recovery tests for Conversation Agent operations."""
import asyncio
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.conversation_agent.contracts import ConversationEvent
from core.conversation_agent.operations import OperationRegistry, OperationState
from core.migrations.runner import run_migrations


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    @contextmanager
    def scope():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    return scope, engine


def test_terminal_operation_replays_after_registry_restart():
    session_scope, engine = _session_factory()
    try:
        first_registry = OperationRegistry(session_factory=session_scope)
        operation, created = first_registry.start(7, "req_" + "p" * 24, "persist me")
        assert created

        async def finish():
            await operation.publish(ConversationEvent(
                "evt_accepted", operation.request_id, operation.session_id,
                "accepted", {"status": "running"},
            ))
            await operation.publish(ConversationEvent(
                "evt_final", operation.request_id, operation.session_id,
                "final", {"status": "completed", "content": "durable result"},
            ))

        asyncio.run(finish())

        restarted_registry = OperationRegistry(session_factory=session_scope)
        restored, created_after_restart = restarted_registry.start(
            7, "req_" + "p" * 24, "persist me"
        )
        assert not created_after_restart
        assert restored.state is OperationState.COMPLETED
        assert restored.matches_message("persist me")

        async def replay():
            return [event async for event in restarted_registry.follow(restored)]

        events = asyncio.run(replay())
        assert [event.type for event in events] == ["accepted", "final"]
        assert events[-1].payload["content"] == "durable result"
    finally:
        engine.dispose()


def test_running_operation_after_restart_is_marked_uncertain_not_reexecuted():
    session_scope, engine = _session_factory()
    try:
        first_registry = OperationRegistry(session_factory=session_scope)
        operation, created = first_registry.start(8, "req_" + "r" * 24, "may have side effects")
        assert created
        assert operation.state is OperationState.RUNNING

        restarted_registry = OperationRegistry(session_factory=session_scope)
        restored, created_after_restart = restarted_registry.start(
            8, "req_" + "r" * 24, "may have side effects"
        )
        assert not created_after_restart
        assert restored.state is OperationState.FAILED
        assert restored.terminal is not None
        assert restored.terminal.payload["error_code"] == "operation_interrupted"
        assert not restored.matches_message("different request body")
    finally:
        engine.dispose()
