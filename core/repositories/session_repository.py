"""Repository for conversation session records."""
from __future__ import annotations

from ..database import ChatSession
from .base import BaseRepository


class SessionRepository(BaseRepository):
    """Owns CRUD operations for conversation session rows."""

    def list_recent(self) -> list[ChatSession]:
        return (
            self.db.query(ChatSession)
            .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
            .all()
        )

    def get(self, session_id: int) -> ChatSession | None:
        return self.db.get(ChatSession, session_id)

    def create(self, title: str = "گفتگوی جدید") -> ChatSession:
        session = ChatSession(title=title)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def delete(self, session: ChatSession) -> None:
        self.db.delete(session)
        self.db.commit()

    def rename(self, session: ChatSession, title: str, *, is_custom: bool = True) -> ChatSession:
        session.title = title
        if hasattr(session, "title_is_custom"):
            session.title_is_custom = is_custom
        self.db.commit()
        self.db.refresh(session)
        return session
