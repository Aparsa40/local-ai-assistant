"""Application service for session and message workflows."""
from __future__ import annotations

from core.repositories import MessageRepository, SessionRepository
from core.permissions.audit import AuditService
from core.permissions.guards import require_access
from core.permissions.manager import PermissionManager
from core.permissions.types import AccessContext, PermissionOperation, ResourceType

from .schemas import ChatPreparation, ConversationMessage


class ConversationNotFoundError(LookupError):
    """Raised when a conversation session does not exist."""


class ConversationService:
    """Coordinates conversation rules while keeping ORM access in repositories."""

    DEFAULT_TITLE = "گفتگوی جدید"

    def __init__(
        self,
        db,
        permission_manager: PermissionManager | None = None,
        access_context: AccessContext | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.permission_manager = permission_manager
        self.access_context = access_context
        self.audit_service = audit_service

    def _authorize(self, session_id: int | str, operation: PermissionOperation) -> None:
        require_access(
            self.permission_manager,
            self.access_context,
            ResourceType.CONVERSATION,
            str(session_id),
            operation,
            audit_service=self.audit_service,
        )

    def list_sessions(self) -> list[dict[str, object]]:
        self._authorize("session-collection", PermissionOperation.READ)
        return [
            {"id": item.id, "title": item.title}
            for item in self.sessions.list_recent()
        ]

    def create_session(self) -> dict[str, object]:
        self._authorize("session-collection", PermissionOperation.CREATE)
        item = self.sessions.create(self.DEFAULT_TITLE)
        return {"id": item.id, "title": item.title}

    def delete_session(self, session_id: int) -> dict[str, object]:
        self._authorize(session_id, PermissionOperation.DELETE)
        item = self.sessions.get(session_id)
        if item is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        self.sessions.delete(item)
        return {"status": "success", "deleted_session_id": session_id}

    def rename_session(self, session_id: int, title: str) -> dict[str, object]:
        self._authorize(session_id, PermissionOperation.UPDATE)
        item = self.sessions.get(session_id)
        if item is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        normalized = title.strip()
        if not normalized:
            raise ValueError("عنوان نشست نمی‌تواند خالی باشد")
        item = self.sessions.rename(item, normalized, is_custom=True)
        return {"id": item.id, "title": item.title}

    def get_messages(self, session_id: int) -> list[dict[str, str | None]]:
        self._authorize(session_id, PermissionOperation.READ)
        if self.sessions.get(session_id) is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        return [
            {"role": item.role, "content": item.content, "model": item.model_used}
            for item in self.messages.list_for_session(session_id)
        ]

    def get_recent_messages(self, session_id: int, *, limit: int = 20) -> tuple[ConversationMessage, ...]:
        """Return a bounded chronological history slice with source identifiers."""
        # Context assembly may request one extra row to exclude the already-persisted
        # current user turn while still retaining the requested number of prior turns.
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 101:
            raise ValueError("تعداد پیام‌های تاریخچه باید بین ۱ تا ۱۰۱ باشد")
        self._authorize(session_id, PermissionOperation.READ)
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
        self._authorize(session_id, PermissionOperation.UPDATE)
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
        self._authorize(session_id, PermissionOperation.UPDATE)
        if self.sessions.get(session_id) is None:
            raise ConversationNotFoundError("نشست یافت نشد")
        self.messages.append(session_id, "assistant", content, model_used=model_used)
