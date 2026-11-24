from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.context import ContextConfigurationError, ContextManager, ContextRequest, ContextValidationError
from core.conversations import ConversationService
from core.database import Base
from core.knowledge import KnowledgeScope, KnowledgeService
from core.migrations import run_migrations
from core.memory import MemoryAccessDeniedError, MemoryScope, MemoryService
from permission_test_helpers import make_test_access


class AllowScopedPolicy:
    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return scope_type in {"user", "conversation"} and owner_id == "local" and scope_id in {"profile-1", "profile-2", "1"}


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def make_services(db, *, allow_memory: bool = True):
    manager, context = make_test_access()
    conversations = ConversationService(db, manager, context)
    memory = MemoryService(db, access_policy=AllowScopedPolicy()) if allow_memory else MemoryService(db)
    return conversations, memory


def add_active_memory(memory, scope, content: str, *, source_ref: str = "profile-preference"):
    candidate = memory.create_candidate(
        scope,
        memory_type="long_term",
        content=content,
        source_type="user",
        source_ref=source_ref,
        provenance={"source": "explicit-user-statement", "note": "reviewed"},
        confidence=95,
        importance=90,
    )
    return memory.activate(scope, candidate.id, verified_by="local-user-review")


def test_context_uses_bounded_recent_history_in_chronological_order_and_skips_current_turn():
    engine, db = make_db()
    try:
        conversations, _ = make_services(db)
        session_id = conversations.create_session()["id"]
        conversations.messages.append(session_id, "user", "پیام قدیمی")
        conversations.messages.append(session_id, "assistant", "پاسخ قدیمی")
        conversations.messages.append(session_id, "user", "پیام نزدیک")
        conversations.messages.append(session_id, "assistant", "پاسخ نزدیک")
        conversations.messages.append(session_id, "user", "درخواست فعلی")

        package = ContextManager(conversations).assemble(
            ContextRequest(conversation_id=session_id, query="درخواست فعلی", history_limit=3)
        )

        assert [item.content for item in package.items] == ["پاسخ قدیمی", "پیام نزدیک", "پاسخ نزدیک"]
        assert all(item.source_type == "conversation" for item in package.items)
        assert all(item.trust_status == "historical_unverified" for item in package.items)
        assert all(item.source_ref.startswith("message:") for item in package.items)
        assert package.knowledge_status == "not_connected"
    finally:
        db.close()
        engine.dispose()


def test_context_retrieves_only_explicit_memory_scopes_and_preserves_provenance():
    engine, db = make_db()
    try:
        conversations, memory = make_services(db)
        session_id = conversations.create_session()["id"]
        scope = MemoryScope("user", "profile-1", "local")
        active = add_active_memory(memory, scope, "کاربر پاسخ فارسی و ساختاریافته را ترجیح می‌دهد")
        conversations.messages.append(session_id, "assistant", active.content)

        package = ContextManager(conversations, memory).assemble(
            ContextRequest(
                conversation_id=session_id,
                query="پاسخ فارسی",
                memory_scopes=(scope,),
            )
        )

        assert len(package.items) == 1
        item = package.items[0]
        assert item.source_type == "memory"
        assert item.source_ref == f"memory:{active.id}"
        assert item.trust_status == "active"
        assert item.provenance["memory_id"] == active.id
        assert item.provenance["source_ref"] == "profile-preference"
        assert item.provenance["verified_by"] == "local-user-review"

        no_memory_package = ContextManager(conversations).assemble(
            ContextRequest(conversation_id=session_id, query="پاسخ فارسی")
        )
        assert all(item.source_type != "memory" for item in no_memory_package.items)
    finally:
        db.close()
        engine.dispose()


def test_context_memory_access_remains_default_deny():
    engine, db = make_db()
    try:
        conversations, memory = make_services(db, allow_memory=False)
        session_id = conversations.create_session()["id"]
        request = ContextRequest(
            conversation_id=session_id,
            query="ترجیح فارسی",
            memory_scopes=(MemoryScope("user", "profile-1", "local"),),
        )
        with pytest.raises(MemoryAccessDeniedError):
            ContextManager(conversations, memory).assemble(request)
    finally:
        db.close()
        engine.dispose()


def test_context_budget_prefers_recent_items_and_reports_omissions():
    engine, db = make_db()
    try:
        conversations, _ = make_services(db)
        session_id = conversations.create_session()["id"]
        conversations.messages.append(session_id, "user", "اولین پیام")
        conversations.messages.append(session_id, "assistant", "پاسخ میانی")
        conversations.messages.append(session_id, "user", "آخرین پیام")
        conversations.messages.append(session_id, "user", "درخواست جاری")

        from core.context.token_budget import TokenBudgetPolicy

        manager = ContextManager(
            conversations,
            token_budget=TokenBudgetPolicy(characters_per_token=100, item_overhead_tokens=12),
        )
        package = manager.assemble(
            ContextRequest(
                conversation_id=session_id,
                query="درخواست جاری",
                history_limit=3,
                max_tokens=32,
            )
        )

        assert package.estimated_tokens <= package.token_budget
        assert package.omitted_items == 1
        assert [item.content for item in package.items] == ["پاسخ میانی", "آخرین پیام"]
    finally:
        db.close()
        engine.dispose()


def test_context_rejects_implicit_cross_owner_memory_scope_and_invalid_limits():
    engine, db = make_db()
    try:
        conversations, _ = make_services(db)
        session_id = conversations.create_session()["id"]
        manager = ContextManager(conversations)
        with pytest.raises(ContextValidationError):
            manager.assemble(
                ContextRequest(
                    conversation_id=session_id,
                    query="درخواست",
                    owner_id="local",
                    memory_scopes=(MemoryScope("user", "profile-1", "another-owner"),),
                )
            )
        with pytest.raises(ContextValidationError):
            manager.assemble(
                ContextRequest(conversation_id=session_id, query="درخواست", max_tokens=10)
            )
    finally:
        db.close()
        engine.dispose()


def test_memory_limit_is_aggregate_across_explicit_scopes():
    engine, db = make_db()
    try:
        conversations, memory = make_services(db)
        session_id = conversations.create_session()["id"]
        scope_one = MemoryScope("user", "profile-1", "local")
        scope_two = MemoryScope("user", "profile-2", "local")
        add_active_memory(memory, scope_one, "ترجیح پاسخ فارسی اول", source_ref="first")
        add_active_memory(memory, scope_two, "ترجیح پاسخ فارسی دوم", source_ref="second")

        package = ContextManager(conversations, memory).assemble(
            ContextRequest(
                conversation_id=session_id,
                query="ترجیح پاسخ فارسی",
                memory_scopes=(scope_one, scope_two),
                memory_limit=1,
            )
        )

        assert len([item for item in package.items if item.source_type == "memory"]) == 1
        assert package.omitted_items >= 1
    finally:
        db.close()
        engine.dispose()


class AllowKnowledgePolicy:
    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return scope_type == "user" and owner_id == "local" and scope_id == "profile-1"


def test_context_retrieves_knowledge_only_from_explicit_authorized_scopes():
    engine, db = make_db()
    try:
        run_migrations(engine)
        conversations, _ = make_services(db)
        session_id = conversations.create_session()["id"]
        scope = KnowledgeScope("user", "profile-1", "local")
        knowledge = KnowledgeService(db, access_policy=AllowKnowledgePolicy())
        source = knowledge.create_source(scope, source_type="text", title="Private reference")
        knowledge.index_extracted_text(
            scope, source.id, "Scoped lexical retrieval keeps source provenance visible."
        )

        package = ContextManager(conversations, knowledge=knowledge).assemble(
            ContextRequest(
                conversation_id=session_id,
                query="scoped lexical",
                knowledge_scopes=(scope,),
            )
        )

        assert package.knowledge_status == "connected"
        assert len(package.items) == 1
        assert package.items[0].source_type == "knowledge"
        assert package.items[0].trust_status == "source_unreviewed"
        assert package.items[0].provenance["source_id"] == source.id
    finally:
        db.close()
        engine.dispose()


def test_context_rejects_knowledge_scope_when_storage_is_not_configured():
    engine, db = make_db()
    try:
        conversations, _ = make_services(db)
        session_id = conversations.create_session()["id"]
        request = ContextRequest(
            conversation_id=session_id,
            query="private knowledge",
            knowledge_scopes=(KnowledgeScope("user", "profile-1", "local"),),
        )
        with pytest.raises(ContextConfigurationError):
            ContextManager(conversations).assemble(request)
    finally:
        db.close()
        engine.dispose()
