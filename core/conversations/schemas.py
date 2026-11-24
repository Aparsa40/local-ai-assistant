"""Typed data contracts for conversation operations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: str
    content: str
    model: str | None = None


@dataclass(frozen=True, slots=True)
class ChatPreparation:
    session_id: int
    history: tuple[ConversationMessage, ...]
