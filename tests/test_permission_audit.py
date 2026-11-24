from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.permissions.audit import AuditPersistenceError, AuditService
from core.permissions.types import (
    PermissionOperation,
    PermissionResource,
    PermissionSubject,
    ResourceType,
    SubjectType,
)
from core.repositories.audit_repository import AuditRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_audit_event_persists_only_allowlisted_redacted_metadata(db_session) -> None:
    service = AuditService(AuditRepository(db_session))
    event = service.record(
        event_type="tool_execution",
        request_id="request-audit-1",
        outcome="denied",
        subject=PermissionSubject(SubjectType.SERVICE, "tool-gateway"),
        resource=PermissionResource(ResourceType.TOOL, "file.read"),
        operation=PermissionOperation.EXECUTE,
        metadata={
            "tool_id": "file.read",
            "reason_code": "no_matching_grant",
            "api_key": "sk-very-secret-value",
            "content": "private document text",
            "exception_type": "Bearer abcdefghijklmnop",
            "unrecognized": "must not be stored",
        },
    )

    stored = AuditRepository(db_session).list_for_request("request-audit-1")

    assert event.metadata == {
        "tool_id": "file.read",
        "reason_code": "no_matching_grant",
        "exception_type": "[REDACTED]",
    }
    assert len(stored) == 1
    assert stored[0]["metadata"] == event.metadata
    assert stored[0]["subject_id"] == "tool-gateway"


def test_audit_service_rejects_non_object_metadata(db_session) -> None:
    service = AuditService(AuditRepository(db_session))

    with pytest.raises(ValueError, match="JSON object"):
        service.record(
            event_type="permission_decision",
            request_id="request-audit-2",
            outcome="deny",
            metadata=["not", "an", "object"],  # type: ignore[arg-type]
        )


def test_audit_repository_exposes_no_update_or_delete_api(db_session) -> None:
    repository = AuditRepository(db_session)

    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_audit_persistence_failure_is_normalized() -> None:
    class BrokenRepository:
        def append(self, event):
            raise RuntimeError("database details must not escape")

    service = AuditService(BrokenRepository())

    with pytest.raises(AuditPersistenceError, match="could not be persisted") as error:
        service.record(
            event_type="permission_decision",
            request_id="request-audit-3",
            outcome="deny",
        )

    assert "database details" not in str(error.value.__cause__)
