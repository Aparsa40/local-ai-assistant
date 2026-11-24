"""Repository for conversation message records."""
from __future__ import annotations

from ..database import ChatMessage
from .base import BaseRepository


class MessageRepository(BaseRepository):
    """Owns message persistence and deterministic per-session ordering."""

    def list_for_session(self, session_id: int) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )

    def list_recent_for_session(self, session_id: int, limit: int) -> list[ChatMessage]:
        """Return the latest bounded slice in chronological presentation order."""
        rows = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))

    def append(
        self,
        session_id: int,
        role: str,
        content: str,
        *,
        model_used: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            model_used=model_used,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message
