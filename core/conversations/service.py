"""Application service for session and message workflows."""
from __future__ import annotations

from core.repositories import MessageRepository, SessionRepository

from .schemas import ChatPreparation, ConversationMessage


class ConversationNotFoundError(LookupError):
    """Raised when a conversation session does not exist."""


class ConversationService:
    """Coordinates conversation rules while keeping ORM access in repositories."""

    DEFAULT_TITLE = "گفتگوی جدید"

    def __init__(self, db) -> None:
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)

    def list_sessions(self) -> list[dict[str, object]]:
        return [
            {"id": item.id, "title": item.title}
            for item in self.sessions.list_recent()
        ]

    def create_session(self) -> dict[str, object]:
        item = self.sessions.create(self.DEFAULT_TITLE)
        return {"id": item.id, "title": item.title}

    def delete_session(self, session_id: int) -> dict[str, object]:
        item = self.sessions.get(session_id)
        if item is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        self.sessions.delete(item)
        return {"status": "success", "deleted_session_id": session_id}

    def rename_session(self, session_id: int, title: str) -> dict[str, object]:
        item = self.sessions.get(session_id)
        if item is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        normalized = title.strip()
        if not normalized:
            raise ValueError("عنوان نشست نمی‌تواند خالی باشد")
        item = self.sessions.rename(item, normalized, is_custom=True)
        return {"id": item.id, "title": item.title}

    def get_messages(self, session_id: int) -> list[dict[str, str | None]]:
        if self.sessions.get(session_id) is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        return [
            {"role": item.role, "content": item.content, "model": item.model_used}
            for item in self.messages.list_for_session(session_id)
        ]

    def get_recent_messages(self, session_id: int, *, limit: int = 20) -> tuple[ConversationMessage, ...]:
        """Return a bounded chronological history slice with source identifiers."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("تعداد پیام‌های تاریخچه باید بین ۱ تا ۱۰۰ باشد")
        if self.sessions.get(session_id) is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        return tuple(
            ConversationMessage(
                role=item.role,
                content=item.content,
                model=item.model_used,
                message_id=item.id,
                timestamp=item.timestamp,
            )
            for item in self.messages.list_recent_for_session(session_id, limit)
        )

    def prepare_chat(self, session_id: int, user_message: str) -> ChatPreparation:
        """Persist the user turn before inference and return prior history."""
        session = self.sessions.get(session_id)
        if session is None:
            raise ConversationNotFoundError("نشست یافت نشد")

        if session.title == self.DEFAULT_TITLE and not session.title_is_custom:
            title = user_message[:35] + ("..." if len(user_message) > 35 else "")
            self.sessions.rename(session, title, is_custom=False)

        self.messages.append(session_id, "user", user_message)
        persisted = self.messages.list_for_session(session_id)
        history = tuple(
            ConversationMessage(
                role=item.role,
                content=item.content,
                model=item.model_used,
                message_id=item.id,
                timestamp=item.timestamp,
            )
            for item in persisted[:-1]
        )
        return ChatPreparation(session_id=session_id, history=history)

    def append_assistant_message(
        self, session_id: int, content: str, model_used: str
    ) -> None:
        if self.sessions.get(session_id) is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        self.messages.append(session_id, "assistant", content, model_used=model_used)
