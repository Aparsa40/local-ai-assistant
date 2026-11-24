from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, MemoryRecord, utcnow_naive
from core.memory import (
    MemoryAccessDeniedError,
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryScope,
    MemoryService,
    MemoryValidationError,
)


class AllowScopedPolicy:
    def __init__(self, owner_id: str = "owner-a", scope_id: str = "profile-1"):
        self.owner_id = owner_id
        self.scope_id = scope_id

    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return scope_type == "user" and scope_id == self.scope_id and owner_id == self.owner_id


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def make_service(db, owner_id: str = "owner-a", scope_id: str = "profile-1"):
    policy = AllowScopedPolicy(owner_id=owner_id, scope_id=scope_id)
    return MemoryService(db, access_policy=policy), MemoryScope("user", scope_id, owner_id)


def create_candidate(service, scope, content="کاربر توسعه‌دهنده پایتون است", **kwargs):
    return service.create_candidate(
        scope,
        memory_type=kwargs.pop("memory_type", "long_term"),
        content=content,
        source_type=kwargs.pop("source_type", "user"),
        provenance=kwargs.pop("provenance", {"source": "explicit-user-statement"}),
        **kwargs,
    )


def test_memory_access_is_default_deny():
    engine, db = make_db()
    try:
        service = MemoryService(db)
        with pytest.raises(MemoryAccessDeniedError):
            service.create_candidate(
                MemoryScope("user", "profile-1"),
                memory_type="long_term",
                content="A stable preference",
                source_type="user",
                provenance={"source": "user"},
            )
    finally:
        db.close()
        engine.dispose()


def test_candidate_requires_explicit_activation_before_normal_retrieval():
    engine, db = make_db()
    try:
        service, scope = make_service(db)
        candidate = create_candidate(service, scope)
        assert candidate.status == "candidate"
        assert service.retrieve(scope, "پایتون") == []
        assert len(service.retrieve(scope, "پایتون", include_candidates=True)) == 1

        active = service.activate(scope, candidate.id, verified_by="user-review")
        assert active.status == "active"
        assert active.verified_by == "user-review"
        results = service.retrieve(scope, "پایتون")
        assert len(results) == 1
        assert results[0].memory.id == candidate.id
        assert results[0].matched_terms == ("پایتون",)
    finally:
        db.close()
        engine.dispose()


def test_deduplication_is_idempotent_and_conflicting_keys_are_rejected():
    engine, db = make_db()
    try:
        service, scope = make_service(db)
        first = create_candidate(service, scope, "ترجیح می‌دهد پاسخ‌ها فارسی باشند", dedup_key="language-pref")
        duplicate = create_candidate(service, scope, " ترجیح می‌دهد پاسخ‌ها فارسی باشند ", dedup_key="language-pref")
        assert duplicate.id == first.id

        with pytest.raises(MemoryConflictError):
            create_candidate(service, scope, "ترجیح می‌دهد پاسخ‌ها انگلیسی باشند", dedup_key="language-pref")
    finally:
        db.close()
        engine.dispose()


def test_scope_and_owner_isolation_prevent_cross_scope_reads():
    engine, db = make_db()
    try:
        owner_a, scope_a = make_service(db, "owner-a", "profile-1")
        owner_b, scope_b = make_service(db, "owner-b", "profile-1")
        item = create_candidate(owner_a, scope_a, "علاقه‌مند به هوش مصنوعی است")
        with pytest.raises(MemoryNotFoundError):
            owner_b.get(scope_b, item.id)

        different_scope = MemoryService(db, access_policy=AllowScopedPolicy("owner-a", "profile-1"))
        with pytest.raises(MemoryAccessDeniedError):
            different_scope.get(MemoryScope("user", "profile-2", "owner-a"), item.id)
    finally:
        db.close()
        engine.dispose()


def test_validation_requires_provenance_and_rejects_secret_material():
    engine, db = make_db()
    try:
        service, scope = make_service(db)
        with pytest.raises(MemoryValidationError):
            create_candidate(service, scope, provenance={})
        with pytest.raises(MemoryValidationError):
            create_candidate(service, scope, "api_key=sk-abcdefghijklmnop")
        with pytest.raises(MemoryValidationError):
            create_candidate(service, scope, provenance={"source": "user", "metadata": {"api_key": "very-secret-value"}})
        with pytest.raises(MemoryValidationError):
            create_candidate(service, scope, provenance={"source": "user", "note": "password=not-safe"})
        with pytest.raises(MemoryValidationError):
            create_candidate(service, scope, confidence=101)
    finally:
        db.close()
        engine.dispose()


def test_update_tracks_revision_and_supersede_links_replacement():
    engine, db = make_db()
    try:
        service, scope = make_service(db)
        old = create_candidate(service, scope, "از پاسخ کوتاه خوشش می‌آید", dedup_key="response-style")
        old = service.activate(scope, old.id, verified_by="user-review")
        revised = service.update(scope, old.id, content="پاسخ‌های ساختاریافته را ترجیح می‌دهد", importance=90)
        assert revised.content == "پاسخ‌های ساختاریافته را ترجیح می‌دهد"
        assert len(revised.provenance["revision_history"]) == 1

        duplicate = create_candidate(service, scope, "محتوای جایگزین برای آزمون", dedup_key="another-key")
        with pytest.raises(MemoryConflictError):
            service.update(scope, old.id, content=duplicate.content)

        replacement = create_candidate(service, scope, "ترجیح پاسخ ساختاریافته و دقیق", dedup_key="response-style-v2")
        replacement = service.activate(scope, replacement.id, verified_by="user-review")
        superseded = service.supersede(scope, old.id, replacement.id)
        assert superseded.status == "superseded"
        assert superseded.superseded_by_id == replacement.id
    finally:
        db.close()
        engine.dispose()


def test_retention_expiry_and_explicit_deletion():
    engine, db = make_db()
    try:
        service, scope = make_service(db)
        expiring = create_candidate(service, scope, "موضوع موقت برای پیگیری", memory_type="short_term")
        row = db.query(MemoryRecord).filter(MemoryRecord.id == expiring.id).one()
        row.expires_at = utcnow_naive() - timedelta(seconds=1)
        db.commit()

        assert service.retrieve(scope, "موقت") == []
        assert row.status == "candidate"
        assert service.expire_due(scope) == 1
        with pytest.raises(MemoryNotFoundError):
            service.get(scope, expiring.id)

        removable = create_candidate(service, scope, "یک مورد قابل حذف")
        service.delete(scope, removable.id)
        assert db.query(MemoryRecord).filter(MemoryRecord.id == removable.id).count() == 0
    finally:
        db.close()
        engine.dispose()
