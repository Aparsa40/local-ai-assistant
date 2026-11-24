"""Typed data contracts for conversation operations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: str
    content: str
    model: str | None = None
    message_id: int | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChatPreparation:
    session_id: int
    history: tuple[ConversationMessage, ...]
