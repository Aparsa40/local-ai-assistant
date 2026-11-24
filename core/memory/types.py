"""Typed memory domain contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MemoryType = Literal["short_term", "long_term", "episodic", "semantic"]
MemoryStatus = Literal["candidate", "active", "superseded", "expired"]


@dataclass(frozen=True, slots=True)
class MemoryScope:
    scope_type: str
    scope_id: str
    owner_id: str = "local"


@dataclass(frozen=True, slots=True)
class MemoryRecordView:
    id: int
    memory_type: str
    content: str
    scope_type: str
    scope_id: str
    owner_id: str
    source_type: str
    source_ref: str | None
    provenance: dict
    confidence: int
    importance: int
    status: str
    verified_by: str | None
    retention_days: int | None
    expires_at: datetime | None
    superseded_by_id: int | None
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    memory: MemoryRecordView
    score: float
    matched_terms: tuple[str, ...]
