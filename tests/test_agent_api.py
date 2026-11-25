"""Phase 6 API regression tests for the bounded /api/agents endpoints."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import main as app_module
from core.agents.builtins import AGENT_ID, AGENT_VERSION
from core.agents.contracts import AgentBudgets, AgentDefinition, CompletionCriteria
from core.database import Base
from core.permissions.types import (
    AccessContext,
    PermissionScope,
    PermissionSubject,
    ScopeType,
    SubjectType,
)

RUN_RESPONSE_KEYS = {
    "run_id", "task_id", "agent_id", "agent_version", "status", "attempt",
    "iteration", "tool_calls", "model_tokens", "pending_approval_id",
    "stop_reason", "error_code", "error_message", "outcome", "version",
    "created_at", "started_at", "finished_at",
}

DEFINITION_RESPONSE_KEYS = {
    "agent_id", "version", "goal", "description", "completion", "budgets",
    "allowed_tools", "allowed_models", "data_scopes", "approval_policy", "enabled",
}


def make_unbounded_definition(**overrides) -> AgentDefinition:
    values = dict(
        agent_id="untrusted-api-agent",
        version="1.0.0",
        goal="A bounded goal.",
        description="A bounded description.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        completion=CompletionCriteria(kind="sources_collected", description="One source."),
        budgets=AgentBudgets(max_iterations=2, max_tool_calls=1),
        allowed_tools=("knowledge_search",),
        allowed_models=(),
        data_scopes=("knowledge",),
        approval_policy="explicit",
        enabled=True,
    )
    values.update(overrides)
    return AgentDefinition(**values)


@pytest.fixture
def agent_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed_db = factory()
    try:
        app_module.agent_container.register_builtin_agents(seed_db)
        seed_db.commit()
    finally:
        seed_db.close()

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    def override_access():
        return AccessContext(
            subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
            scope=PermissionScope(ScopeType.LOCAL, "local-machine", "local-user"),
            request_id="agent-api-test-request",
        )

    app_module.app.dependency_overrides[app_module.get_db] = override_db
    app_module.app.dependency_overrides[app_module.get_local_access_context] = override_access
    try:
        with TestClient(app_module.app) as client:
            yield client, factory
    finally:
        app_module.app.dependency_overrides.clear()
        engine.dispose()


def _agent_task_payload(**overrides):
    payload = {
        "agent_id": AGENT_ID,
        "agent_version": AGENT_VERSION,
        "title": "Analyze private notes",
        "query": "durable storage",
        "scope_type": "user",
        "scope_id": "private-notes",
    }
    payload.update(overrides)
    return payload


def test_agent_endpoints_reject_non_loopback_clients():
    with TestClient(app_module.app) as client:
        assert client.get("/api/agents").status_code == 403
        assert client.get("/api/agents/runs").status_code == 403
        assert client.get("/api/agents/runs/" + "0" * 32).status_code == 403
        assert client.post("/api/agents/tasks", json={}).status_code == 403
        assert client.post("/api/agents/runs/x/execute").status_code == 403
        assert client.post("/api/agents/runs/x/pause").status_code == 403
        assert client.post("/api/agents/runs/x/resume").status_code == 403
        assert client.post("/api/agents/runs/x/cancel").status_code == 403


def test_agent_api_rejects_cross_origin_browser_requests():
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/agents",
        "raw_path": b"/api/agents",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"origin", b"https://attacker.example"),
        ],
        "client": ("127.0.0.1", 45678),
        "server": ("127.0.0.1", 8000),
    })
    with pytest.raises(HTTPException) as denied:
        app_module.get_local_access_context(request)
    assert denied.value.status_code == 403

    same_origin = Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/agents",
        "raw_path": b"/api/agents",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"origin", b"http://127.0.0.1:8000"),
        ],
        "client": ("127.0.0.1", 45678),
        "server": ("127.0.0.1", 8000),
    })
    accepted = app_module.get_local_access_context(same_origin)
    assert accepted.subject.subject_id == "local-api"


def test_agent_api_lists_the_builtin_definition_with_safe_serialization(agent_client):
    client, _ = agent_client
    response = client.get("/api/agents")
    assert response.status_code == 200
    agents = response.json()["agents"]
    builtins = [item for item in agents if item["agent_id"] == AGENT_ID]
    assert builtins and builtins[0]["version"] == AGENT_VERSION
    assert builtins[0]["allowed_tools"] == ["knowledge_search"]
    assert builtins[0]["allowed_models"] == []
    assert builtins[0]["enabled"] is True
    assert set(builtins[0]) == DEFINITION_RESPONSE_KEYS


def test_agent_api_rejects_unknown_agents_and_missing_runs(agent_client):
    client, _ = agent_client
    unknown_agent = client.post("/api/agents/tasks", json=_agent_task_payload(
        agent_id="no-such-agent",
    ))
    assert unknown_agent.status_code == 422

    run_id = "0" * 32
    missing = client.get(f"/api/agents/runs/{run_id}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Agent run not found."
    assert client.post(f"/api/agents/runs/{run_id}/execute").status_code == 404
    assert client.post(f"/api/agents/runs/{run_id}/pause").status_code == 404
    assert client.post(f"/api/agents/runs/{run_id}/resume").status_code == 404
    assert client.post(f"/api/agents/runs/{run_id}/cancel").status_code == 404

    invalid_limit = client.get("/api/agents/runs", params={"limit": 0})
    assert invalid_limit.status_code == 422


def test_agent_api_task_and_run_creation_uses_safe_run_serialization(agent_client):
    client, _ = agent_client
    created = client.post("/api/agents/tasks", json=_agent_task_payload())
    assert created.status_code == 200, created.text
    run = created.json()["run"]
    assert set(run) == RUN_RESPONSE_KEYS
    assert run["status"] == "pending"
    assert run["error_code"] is None
    assert len(run["run_id"]) == 32

    status = client.get(f"/api/agents/runs/{run['run_id']}")
    assert status.status_code == 200
    assert status.json()["run"]["run_id"] == run["run_id"]
    events = status.json()["events"]
    assert [item["event_type"] for item in events] == ["run_created"]
    assert set(events[0]) == {"event_type", "outcome", "metadata", "created_at"}
    # Whitelisted redacted metadata only; raw prompts and tool outputs never appear.
    assert not ({"prompt", "content", "query", "results"} & set(events[0]["metadata"]))


def test_agent_api_transitions_reject_invalid_states(agent_client):
    client, _ = agent_client
    created = client.post("/api/agents/tasks", json=_agent_task_payload())
    run_id = created.json()["run"]["run_id"]

    paused = client.post(f"/api/agents/runs/{run_id}/pause")
    assert paused.status_code == 409  # PENDING -> PAUSED is not a legal transition

    cancelled = client.post(f"/api/agents/runs/{run_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["run"]["status"] == "cancelled"

    again = client.post(f"/api/agents/runs/{run_id}/cancel")
    assert again.status_code == 409  # terminal states absorb

    executed = client.post(f"/api/agents/runs/{run_id}/execute")
    assert executed.status_code == 409  # finished runs cannot execute


def test_agent_api_resume_rejects_undecided_approval_handoffs(agent_client):
    client, factory = agent_client
    created = client.post("/api/agents/tasks", json=_agent_task_payload())
    run_id = created.json()["run"]["run_id"]

    db = factory()
    try:
        services = app_module.agent_container.build_services(db)
        started = services.lifecycle.start(run_id, expected_version=1)
        services.lifecycle.pause_for_approval(
            run_id, expected_version=started.version, approval_id="approval-missing",
        )
    finally:
        db.close()

    # The handoff must not resolve without a decided owner approval.
    resumed = client.post(f"/api/agents/runs/{run_id}/resume")
    assert resumed.status_code == 409
    assert "decided" in resumed.json()["detail"]


def test_agent_api_execute_fails_closed_without_a_trusted_behavior(agent_client):
    client, factory = agent_client
    db = factory()
    try:
        services = app_module.agent_container.build_services(db)
        services.registry.register(make_unbounded_definition())
        db.commit()
    finally:
        db.close()

    created = client.post("/api/agents/tasks", json=_agent_task_payload(
        agent_id="untrusted-api-agent",
    ))
    assert created.status_code == 200, created.text
    run_id = created.json()["run"]["run_id"]

    executed = client.post(f"/api/agents/runs/{run_id}/execute")
    assert executed.status_code == 409
    assert "behavior" in executed.json()["detail"]

    db = factory()
    try:
        services = app_module.agent_container.build_services(db)
        run = services.lifecycle.get_run(run_id)
        assert run.status.value == "pending"
        assert services.lifecycle.has_executor(run_id) is False
    finally:
        db.close()
