import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from main import app, get_db, get_local_access_context
from core.permissions.types import AccessContext, PermissionScope, PermissionSubject, ScopeType, SubjectType


def override_local_access_context():
    return AccessContext(
        subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
        scope=PermissionScope(ScopeType.LOCAL, "local-machine", "local-user"),
    )


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_local_access_context] = override_local_access_context
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_session_title_can_be_renamed_and_persists(client):
    created = client.post("/api/sessions")
    session_id = created.json()["id"]

    response = client.patch(f"/api/sessions/{session_id}", json={"title": "جلسه طراحی معماری"})

    assert response.status_code == 200
    assert response.json() == {"id": session_id, "title": "جلسه طراحی معماری"}
    assert client.get("/api/sessions").json()[0]["title"] == "جلسه طراحی معماری"


def test_session_rename_rejects_empty_or_whitespace_title(client):
    created = client.post("/api/sessions")
    session_id = created.json()["id"]

    empty_response = client.patch(f"/api/sessions/{session_id}", json={"title": ""})
    whitespace_response = client.patch(f"/api/sessions/{session_id}", json={"title": "   "})

    assert empty_response.status_code == 422
    assert whitespace_response.status_code == 422


def test_session_rename_returns_404_for_unknown_session(client):
    response = client.patch("/api/sessions/999999", json={"title": "نام جدید"})

    assert response.status_code == 404


def test_session_can_be_deleted_and_is_removed_from_history(client):
    created = client.post("/api/sessions")
    session_id = created.json()["id"]

    response = client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "deleted_session_id": session_id}
    assert all(item["id"] != session_id for item in client.get("/api/sessions").json())
    assert client.get(f"/api/sessions/{session_id}/messages").status_code == 404


def test_session_delete_returns_404_for_unknown_session(client):
    response = client.delete("/api/sessions/999999")

    assert response.status_code == 404
