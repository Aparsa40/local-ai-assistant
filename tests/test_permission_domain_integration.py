from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.context import ContextManager, ContextRequest
from core.conversations import ConversationService
from core.database import Base
from core.memory import MemoryAccessDeniedError, MemoryScope, MemoryService
from core.permissions.guards import AccessDeniedError, require_access
from core.permissions.local_policy import LocalApplicationPolicy
from core.permissions.manager import PermissionManager
from core.permissions.memory_adapter import PermissionManagerMemoryAccessPolicy
from core.permissions.types import (
    AccessContext,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.profiles import ProfileService


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def local_context(owner_id="local-user"):
    return AccessContext(
        subject=PermissionSubject(SubjectType.SERVICE, "local-api"),
        scope=PermissionScope(ScopeType.LOCAL, "local-machine", owner_id),
    )


def local_manager():
    return PermissionManager(policies=(LocalApplicationPolicy(),))


def test_local_policy_allows_only_local_owner_conversation_and_profile_operations():
    manager = local_manager()
    context = local_context()

    require_access(
        manager,
        context,
        ResourceType.CONVERSATION,
        "42",
        PermissionOperation.READ,
    )
    require_access(
        manager,
        context,
        ResourceType.PROFILE,
        "local-user",
        PermissionOperation.UPDATE,
    )

    with pytest.raises(AccessDeniedError):
        require_access(
            manager,
            local_context(owner_id="another-owner"),
            ResourceType.CONVERSATION,
            "42",
            PermissionOperation.READ,
        )


def test_local_policy_denies_credentials_and_unimplemented_domains():
    manager = local_manager()
    context = local_context()
    request = context.build_request(
        PermissionResource(ResourceType.PROVIDER_CREDENTIAL, "openrouter"),
        PermissionOperation.READ,
    )

    assert manager.authorize(request).effect.value == "deny"


def test_conversation_and_profile_services_fail_closed_without_access_context():
    engine, db = make_db()
    try:
        with pytest.raises(AccessDeniedError):
            ConversationService(db).list_sessions()
        with pytest.raises(AccessDeniedError):
            ProfileService(db).serialize()
    finally:
        db.close()
        engine.dispose()


def test_memory_service_uses_central_permission_manager_adapter():
    engine, db = make_db()
    try:
        manager = local_manager()
        subject = PermissionSubject(SubjectType.SERVICE, "local-api")
        policy = PermissionManagerMemoryAccessPolicy(manager, subject)
        memory = MemoryService(db, access_policy=policy)
        scope = MemoryScope("user", "profile-1", "local-user")

        candidate = memory.create_candidate(
            scope,
            memory_type="long_term",
            content="The local owner prefers concise technical explanations.",
            source_type="user",
            provenance={"source": "explicit-user-statement"},
        )
        active = memory.activate(scope, candidate.id, verified_by="local-user")

        assert active.status == "active"
        assert memory.retrieve(scope, "technical explanations")
    finally:
        db.close()
        engine.dispose()


def test_memory_adapter_denies_wrong_owner_and_unknown_actions():
    manager = local_manager()
    policy = PermissionManagerMemoryAccessPolicy(
        manager,
        PermissionSubject(SubjectType.SERVICE, "local-api"),
    )

    assert not policy.authorize("user", "profile-1", "another-owner", "read")
    assert not policy.authorize("user", "profile-1", "local-user", "grant")


def test_context_manager_uses_authorized_conversation_and_explicit_memory_scope():
    engine, db = make_db()
    try:
        manager = local_manager()
        context = local_context()
        conversations = ConversationService(db, manager, context)
        memory_policy = PermissionManagerMemoryAccessPolicy(manager, context.subject)
        memory = MemoryService(db, access_policy=memory_policy)
        session_id = conversations.create_session()["id"]
        scope = MemoryScope("user", "profile-1", "local-user")
        candidate = memory.create_candidate(
            scope,
            memory_type="long_term",
            content="The user prefers Persian technical answers.",
            source_type="user",
            provenance={"source": "explicit-user-statement"},
        )
        memory.activate(scope, candidate.id, verified_by="local-user")

        package = ContextManager(conversations, memory).assemble(
            ContextRequest(
                conversation_id=session_id,
                query="Persian technical answers",
                owner_id="local-user",
                memory_scopes=(scope,),
            )
        )

        assert len(package.items) == 1
        assert package.items[0].source_type == "memory"
    finally:
        db.close()
        engine.dispose()
