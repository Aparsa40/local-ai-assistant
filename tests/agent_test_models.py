"""Shared composed environment for the WP-6.7 Agent Runtime tests.

Builds exactly the application composition used in production:
Base.metadata + run_migrations + AgentRuntimeContainer with its builtin
read-only knowledge tool. The container receives a storage session factory
bound to the same SQLite database file, mirroring the application storage
manager contract. The only replaced component is the InterfaceManager,
which records provider calls and never touches a network provider.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.agents.bootstrap import AgentRuntimeContainer
from core.agents.contracts import AgentBudgets, AgentDefinition, CompletionCriteria
from core.database import Base
from core.knowledge import KnowledgeScope, KnowledgeService
from core.migrations import CURRENT_SCHEMA_REVISION, run_migrations

OWNER_ID = "local-user"
CUSTOM_AGENT_ID = "scripted-test-agent"


class TestKnowledgeSeedPolicy:
    """Allows writes into the test user knowledge scopes only."""

    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return scope_type == "user" and owner_id == OWNER_ID


class FileSessionStorage:
    """Mirrors storage_manager.session() with independent engine connections."""

    def __init__(self, db_path) -> None:
        self._engine = create_engine(
            "sqlite:///" + str(db_path),
            connect_args={"check_same_thread": False},
        )
        self._factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    @contextlib.contextmanager
    def session(self):
        db = self._factory()
        try:
            yield db
        finally:
            db.close()

    def dispose(self) -> None:
        self._engine.dispose()


class FakeInterfaceManager:
    """Records stream chats; never touches a provider."""

    def __init__(self, chunks=(), error=None) -> None:
        self.chunks = tuple(chunks)
        self.error = error
        self.calls = []

    async def stream_chat(self, provider_id, messages, model=None, temperature=None):
        self.calls.append(
            {
                "provider_id": provider_id,
                "model": model,
                "messages": list(messages),
                "temperature": temperature,
            }
        )
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


class ScriptedBehavior:
    """Trusted behavior stub returning a fixed program of decisions.

    The final decision is repeated once the program is exhausted so that
    budget and concurrency paths can drive repeated steps.
    """

    def __init__(self, decisions) -> None:
        self._decisions = list(decisions)
        self._repeat = decisions[-1] if decisions else {"kind": "noop"}
        self.calls = 0

    def decide(self, ctx, state) -> dict:
        self.calls += 1
        if self.calls <= len(self._decisions):
            return self._decisions[self.calls - 1]
        return self._repeat


class _Env:
    """One composed agent runtime over a private SQLite database file."""

    def __init__(self, engine, session, container, services, storage, interface_manager) -> None:
        self.engine = engine
        self.session = session
        self.container = container
        self.services = services
        self._storage = storage
        self.interface_manager = interface_manager

    # -- scope helpers ------------------------------------------------------

    def knowledge_scope(self, scope_id="agent-scope"):
        return KnowledgeScope("user", scope_id, OWNER_ID)

    def data_scope(self, scope_id="agent-scope"):
        from core.agents.contracts import DataScope

        return DataScope("knowledge", "user", scope_id, OWNER_ID)

    # -- seeding and inspection ----------------------------------------------

    def seed_knowledge(self, scope, text: str, *, title="Seeded source"):
        service = KnowledgeService(self.session, access_policy=TestKnowledgeSeedPolicy())
        source = service.create_source(scope, source_type="text", title=title)
        service.index_extracted_text(scope, source.id, text)
        return source

    def run_events(self, run_id: str):
        return self.services.events.repository.list_for_run(run_id, limit=200)

    def checkpoints(self, run_id: str):
        return self.services.checkpoints.list_for_run(run_id, limit=100)

    def event_types(self, run_id: str):
        return tuple(event["event_type"] for event in self.run_events(run_id))

    def events_of_type(self, run_id: str, event_type: str):
        return [
            event for event in self.run_events(run_id)
            if event["event_type"] == event_type
        ]

    # -- execution ------------------------------------------------------------

    def execute(self, run_id: str):
        return asyncio.run(self.services.controller.execute(run_id))

    def dispose(self) -> None:
        self.session.close()
        self._storage.dispose()
        self.engine.dispose()


def compose_on(db_path) -> _Env:
    """Compose the full Agent Runtime on an existing or new database file."""
    engine = create_engine(
        "sqlite:///" + str(db_path),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    assert run_migrations(engine) == CURRENT_SCHEMA_REVISION
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    storage = FileSessionStorage(db_path)
    interface = FakeInterfaceManager()
    container = AgentRuntimeContainer(storage, interface)
    container.register_builtin_agents(session)
    services = container.build_services(session)
    return _Env(engine, session, container, services, storage, interface)


def make_agent_env(tmp_path) -> _Env:
    """Compose the runtime on a private SQLite database file."""
    return compose_on(Path(tmp_path) / "agent-runtime.db")


def make_definition(
    *,
    agent_id=CUSTOM_AGENT_ID,
    version="1.0.0",
    goal="A scripted, bounded test agent.",
    allowed_tools=(),
    allowed_models=(),
    data_scopes=("knowledge",),
    budgets=None,
    completion=None,
    input_schema=None,
) -> AgentDefinition:
    """Build a bounded, valid AgentDefinition for scripted behavior tests."""
    if budgets is None:
        budgets = AgentBudgets(max_iterations=6, max_tool_calls=10)
    if completion is None:
        completion = CompletionCriteria(
            kind="structured_result_present",
            description="A structured result was reported.",
        )
    if input_schema is None:
        input_schema = {"type": "object", "additionalProperties": True}
    return AgentDefinition(
        agent_id=agent_id,
        version=version,
        goal=goal,
        description="A deterministic scripted agent used by the Phase 6 tests.",
        input_schema=input_schema,
        output_schema={"type": "object"},
        completion=completion,
        budgets=budgets,
        allowed_tools=tuple(allowed_tools),
        allowed_models=tuple(allowed_models),
        data_scopes=tuple(data_scopes),
        approval_policy="explicit",
    )


def make_search_input(run_id: str, scope, *, limit=5) -> dict:
    return {
        "run_id": run_id,
        "scope_type": scope.scope_type,
        "scope_id": scope.scope_id,
        "owner_id": scope.owner_id,
        "query": "durable storage",
        "limit": limit,
    }
