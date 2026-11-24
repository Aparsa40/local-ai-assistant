"""WP-6.2 / WP-6.7 regression tests for the trusted Agent Registry."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.agents.contracts import AgentDefinition, AgentDefinitionError
from core.agents.registry import AgentRegistry
from core.database import Base
from core.migrations import CURRENT_SCHEMA_REVISION, run_migrations
from core.repositories.agent_repository import AgentDefinitionRepository


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    assert run_migrations(engine) == CURRENT_SCHEMA_REVISION
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def make_definition(**overrides) -> AgentDefinition:
    from core.agents.contracts import AgentBudgets, CompletionCriteria

    values = dict(
        agent_id="registry-agent",
        version="1.0.0",
        goal="A valid bounded goal.",
        description="A valid bounded description.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        completion=CompletionCriteria(
            kind="sources_collected", description="One source collected."
        ),
        budgets=AgentBudgets(max_iterations=3, max_tool_calls=2),
        allowed_tools=("knowledge_search",),
        allowed_models=(),
        data_scopes=("knowledge",),
        approval_policy="explicit",
        enabled=True,
    )
    values.update(overrides)
    return AgentDefinition(**values)


def test_register_persists_and_round_trips_the_definition():
    engine, session = _make_session()
    try:
        registry = AgentRegistry(AgentDefinitionRepository(session))
        stored = registry.register(make_definition())
        loaded = registry.get("registry-agent", "1.0.0")
        assert stored == loaded == make_definition()
        assert loaded.budgets.max_iterations == 3
        assert loaded.allowed_tools == ("knowledge_search",)
    finally:
        session.close()
        engine.dispose()


def test_duplicate_version_registration_is_rejected():
    engine, session = _make_session()
    try:
        registry = AgentRegistry(AgentDefinitionRepository(session))
        registry.register(make_definition())
        with pytest.raises(AgentDefinitionError, match="already"):
            registry.register(make_definition())
    finally:
        session.close()
        engine.dispose()


def test_persisted_duplicate_registration_is_rejected_too():
    engine, session = _make_session()
    try:
        repository = AgentDefinitionRepository(session)
        first = AgentRegistry(repository)
        first.register(make_definition())
        second = AgentRegistry(repository)
        with pytest.raises(AgentDefinitionError, match="already"):
            second.register(make_definition())
    finally:
        session.close()
        engine.dispose()


def test_second_version_of_the_same_agent_registers_separately():
    engine, session = _make_session()
    try:
        registry = AgentRegistry(AgentDefinitionRepository(session))
        registry.register(make_definition())
        upgraded = make_definition(
            version="1.1.0",
            goal="An upgraded bounded goal.",
        )
        registry.register(upgraded)
        assert registry.get("registry-agent", "1.0.0").goal != upgraded.goal
        assert registry.get("registry-agent", "1.1.0") == upgraded
    finally:
        session.close()
        engine.dispose()


def test_unknown_definitions_are_rejected():
    engine, session = _make_session()
    try:
        registry = AgentRegistry(AgentDefinitionRepository(session))
        with pytest.raises(AgentDefinitionError, match="unknown"):
            registry.get("registry-agent", "1.0.0")
        with pytest.raises(AgentDefinitionError, match="unknown"):
            registry.get_enabled("registry-agent", "1.0.0")
    finally:
        session.close()
        engine.dispose()


def test_disabled_definitions_are_hidden_from_get_enabled():
    engine, session = _make_session()
    try:
        repository = AgentDefinitionRepository(session)
        registry = AgentRegistry(repository)
        registry.register(make_definition())
        assert repository.set_enabled("registry-agent", "1.0.0", False) is not None
        assert registry.get("registry-agent", "1.0.0").enabled is False
        with pytest.raises(AgentDefinitionError, match="disabled"):
            registry.get_enabled("registry-agent", "1.0.0")
    finally:
        session.close()
        engine.dispose()


def test_returned_definitions_are_deep_copies():
    engine, session = _make_session()
    try:
        registry = AgentRegistry(AgentDefinitionRepository(session))
        registry.register(make_definition())
        first = registry.get("registry-agent", "1.0.0")
        mutated = first.input_schema.copy()
        mutated["type"] = "mutated"
        first.input_schema.clear()
        first.input_schema.update(mutated)
        second = registry.get("registry-agent", "1.0.0")
        assert second.input_schema == {"type": "object"}
    finally:
        session.close()
        engine.dispose()


def test_set_enabled_rejects_unknown_definitions():
    engine, session = _make_session()
    try:
        registry = AgentRegistry(AgentDefinitionRepository(session))
        with pytest.raises(AgentDefinitionError, match="unknown"):
            registry.set_enabled("registry-agent", "1.0.0", False)
    finally:
        session.close()
        engine.dispose()
