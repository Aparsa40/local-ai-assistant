from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.conversations import ConversationNotFoundError, ConversationService
from core.profiles import ProfileService, ProfileServiceError


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_conversation_service_preserves_fresh_chat_and_history_order():
    engine, db = make_db()
    try:
        service = ConversationService(db)
        created = service.create_session()
        session_id = created["id"]

        first = service.prepare_chat(session_id, "سلام")
        assert first.history == ()
        assert service.get_messages(session_id) == [
            {"role": "user", "content": "سلام", "model": None}
        ]

        service.append_assistant_message(session_id, "درود", "test-model")
        second = service.prepare_chat(session_id, "ادامه بده")

        assert [(item.role, item.content) for item in second.history] == [
            ("user", "سلام"),
            ("assistant", "درود"),
        ]
        messages = service.get_messages(session_id)
        assert [item["role"] for item in messages] == ["user", "assistant", "user"]
        assert messages[1]["model"] == "test-model"
        assert service.list_sessions()[0]["title"] == "سلام"
    finally:
        db.close()
        engine.dispose()


def test_custom_conversation_title_is_not_overwritten_by_chat():
    engine, db = make_db()
    try:
        service = ConversationService(db)
        session_id = service.create_session()["id"]
        service.rename_session(session_id, "عنوان انتخابی")
        service.prepare_chat(session_id, "پیام اول")

        assert service.list_sessions()[0]["title"] == "عنوان انتخابی"
    finally:
        db.close()
        engine.dispose()


def test_conversation_service_reports_missing_sessions():
    engine, db = make_db()
    try:
        service = ConversationService(db)
        for operation in (
            lambda: service.delete_session(999),
            lambda: service.rename_session(999, "عنوان"),
            lambda: service.get_messages(999),
            lambda: service.prepare_chat(999, "پیام"),
        ):
            try:
                operation()
            except ConversationNotFoundError:
                pass
            else:
                raise AssertionError("Expected ConversationNotFoundError")
    finally:
        db.close()
        engine.dispose()


def test_profile_service_validation_and_avatar_lifecycle():
    engine, db = make_db()
    try:
        service = ProfileService(db)
        initial = service.serialize()
        assert initial["username"] == "user"
        assert initial["avatar_configured"] is False

        updated = service.update(" Amir ", " amir_dev ", "amir@example.com")
        assert updated["display_name"] == "Amir"
        assert updated["username"] == "amir_dev"

        try:
            service.update(" ", "user", "")
        except ProfileServiceError as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Expected profile validation error")

        try:
            service.get_avatar()
        except ProfileServiceError as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("Expected missing avatar error")
    finally:
        db.close()
        engine.dispose()
