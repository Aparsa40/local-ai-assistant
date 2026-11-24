from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main as app_module
from core.database import Base
from core.permissions.types import (
    AccessContext,
    PermissionScope,
    PermissionSubject,
    ScopeType,
    SubjectType,
)


@pytest.fixture
def local_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

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
            request_id="api-test-request",
        )

    app_module.app.dependency_overrides[app_module.get_db] = override_db
    app_module.app.dependency_overrides[app_module.get_local_access_context] = override_access
    try:
        with TestClient(app_module.app) as client:
            yield client
    finally:
        app_module.app.dependency_overrides.clear()
        engine.dispose()


def test_knowledge_api_requires_exact_persisted_scope_grant(local_client):
    payload = {
        "scope_type": "user",
        "scope_id": "private-notes",
        "owner_id": "local-user",
        "source_type": "text",
        "title": "Private notes",
    }
    denied = local_client.post("/api/knowledge/sources", json=payload)
    assert denied.status_code == 403

    grant = local_client.post(
        "/api/permissions/grants",
        json={
            "subject_type": "service",
            "subject_id": "local-api",
            "resource_type": "knowledge_source",
            "resource_id": "private-notes",
            "operation": "update",
            "scope_type": "user",
            "scope_id": "private-notes",
            "owner_id": "local-user",
        },
    )
    assert grant.status_code == 200, grant.text

    allowed = local_client.post("/api/knowledge/sources", json=payload)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["title"] == "Private notes"


def test_session_delete_api_requires_and_consumes_owner_approval(local_client):
    created = local_client.post("/api/sessions")
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]

    without_approval = local_client.delete(f"/api/sessions/{session_id}")
    assert without_approval.status_code == 422

    requested = local_client.post(f"/api/permissions/approvals/session-delete/{session_id}")
    assert requested.status_code == 200, requested.text
    approval_id = requested.json()["approval_id"]

    approved = local_client.post(f"/api/permissions/approvals/{approval_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    deleted = local_client.delete(
        f"/api/sessions/{session_id}",
        params={"approval_id": approval_id},
    )
    assert deleted.status_code == 200, deleted.text

    replay = local_client.delete(
        f"/api/sessions/{session_id}",
        params={"approval_id": approval_id},
    )
    assert replay.status_code == 409
