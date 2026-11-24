"""Typed contracts for request-scoped context assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.memory.types import MemoryScope


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """Explicit inputs and limits for one context assembly operation."""

    conversation_id: int
    query: str
    owner_id: str = "local"
    history_limit: int = 20
    memory_limit: int = 10
    max_tokens: int = 4000
    memory_scopes: tuple[MemoryScope, ...] = field(default_factory=tuple)
    include_candidates: bool = False


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One selected source item with traceable provenance."""

    source_type: Literal["conversation", "memory"]
    source_ref: str
    content: str
    relevance_score: float
    trust_status: str
    provenance: dict
    role: str | None = None
    model: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """Immutable result for one request; it is not persisted as memory."""

    conversation_id: int
    query: str
    items: tuple[ContextItem, ...]
    estimated_tokens: int
    token_budget: int
    omitted_items: int
    knowledge_status: Literal["not_connected"] = "not_connected"
