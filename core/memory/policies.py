"""Memory privacy and retention policy contracts.

The default access policy denies every operation. Callers must inject an explicit
policy; this is an integration seam, not a replacement for Phase 5 permissions.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from core.database import utcnow_naive


class MemoryAccessPolicy(Protocol):
    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool: ...


class DenyAllMemoryAccessPolicy:
    """Safe default until an owning application explicitly supplies a policy."""

    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return False


class MemoryRetentionPolicy:
    """Conservative deterministic retention defaults."""

    DEFAULT_DAYS = {
        "short_term": 7,
        "long_term": None,
        "episodic": None,
        "semantic": None,
    }

    def expiry_for(self, memory_type: str, retention_days: int | None):
        days = retention_days
        if days is None:
            days = self.DEFAULT_DAYS[memory_type]
        return utcnow_naive() + timedelta(days=days) if days is not None else None
