"""Loopback HTTP smoke coverage for the Phase 8 chat endpoint."""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from core.context import ContextManager
from core.conversation_agent.operations import OperationRegistry
from core.conversation_agent.service import ConversationAgentService
from core.database import Base
from core.migrations.runner import run_migrations
from core.permissions.types import (
    AccessContext,
    PermissionScope,
    PermissionSubject,
    ScopeType,
    SubjectType,
)


def _access_context():
    return AccessContext(
        subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
        scope=PermissionScope(ScopeType.LOCAL, "local-machine", "local-user"),
    )


class _SmokeInterfaceManager:
    async def stream_chat(self, provider_id, messages, model=None, temperature=None):
        assert provider_id == "openrouter"
        assert model == "smoke/model"
        assert any(message.get("role") == "user" for message in messages)
        yield "Phase 8 HTTP smoke response"


@pytest.fixture
def chat_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    run_migrations(engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def session_scope():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_db
    main.app.dependency_overrides[main.get_local_access_context] = _access_context

    service = ConversationAgentService(
        interface_manager=_SmokeInterfaceManager(),
        conversation_builder=lambda db, access, pm: main.ConversationService(
            db, pm, access, main.build_audit_service(db)
        ),
        context_builder=lambda conversation_service, db, access: ContextManager(conversation_service),
        session_factory=session_scope,
        registry=OperationRegistry(session_factory=session_scope),
        readiness_probe=lambda provider_id, model: True,
    )
    monkeypatch.setattr(main, "conversation_agent_service", service)

    with TestClient(main.app) as client:
        yield client

    main.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_chat_endpoint_streams_validated_final_and_persists_assistant(chat_client):
    session = chat_client.post("/api/sessions")
    assert session.status_code == 200
    session_id = session.json()["id"]

    response = chat_client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Run the Phase 8 HTTP smoke test",
            "request_id": "req_" + "h" * 24,
            "provider_id": "openrouter",
            "model": "smoke/model",
        },
    )

    assert response.status_code == 200
    events = [
        __import__("json").loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert any(event["type"] == "accepted" for event in events)
    assert any(event["type"] == "validation" for event in events)
    final = next(event for event in events if event["type"] == "final")
    assert final["data"]["status"] == "completed"
    assert final["data"]["content"] == "Phase 8 HTTP smoke response"

    messages = chat_client.get(f"/api/sessions/{session_id}/messages")
    assert messages.status_code == 200
    assert any(
        message["role"] == "assistant"
        and message["content"] == "Phase 8 HTTP smoke response"
        for message in messages.json()
    )
