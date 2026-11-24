from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
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
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = testing_session_local()
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


def make_png() -> bytes:
    image = Image.new("RGB", (320, 180), color=(30, 120, 200))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_profile_defaults_and_update_are_persisted(client):
    initial = client.get("/api/profile")
    assert initial.status_code == 200
    assert initial.json()["username"] == "user"
    assert initial.json()["avatar_configured"] is False

    updated = client.patch("/api/profile", json={
        "display_name": "Amir",
        "username": "amir_dev",
        "email": "amir@example.com",
    })
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Amir"
    assert updated.json()["username"] == "amir_dev"
    assert updated.json()["email"] == "amir@example.com"
    assert client.get("/api/profile").json()["username"] == "amir_dev"


def test_avatar_upload_is_normalized_and_can_be_deleted(client):
    uploaded = client.put(
        "/api/profile/avatar",
        content=make_png(),
        headers={"Content-Type": "image/png"},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["avatar_configured"] is True

    avatar = client.get("/api/profile/avatar")
    assert avatar.status_code == 200
    assert avatar.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(avatar.content)) as image:
        assert image.size == (256, 256)

    deleted = client.delete("/api/profile/avatar")
    assert deleted.status_code == 200
    assert deleted.json()["avatar_configured"] is False
    assert client.get("/api/profile/avatar").status_code == 404


def test_avatar_upload_rejects_invalid_file(client):
    response = client.put(
        "/api/profile/avatar",
        content=b"not-an-image",
        headers={"Content-Type": "image/png"},
    )
    assert response.status_code == 422


def test_profile_rejects_invalid_email(client):
    response = client.patch("/api/profile", json={
        "display_name": "Test",
        "username": "test",
        "email": "not-an-email",
    })
    assert response.status_code == 422
