"""Stable cross-source ranking helpers for context candidates."""

from __future__ import annotations

from .schemas import ContextItem


def conversation_recency_score(index: int, total: int) -> float:
    """Score chronological history so newer messages are considered first."""
    if total <= 0:
        return 0.0
    return 0.55 + 0.45 * ((index + 1) / total)


def selection_key(item: ContextItem) -> tuple[float, int, str]:
    """Higher relevance first; memory wins exact ties; source reference breaks ties."""
    source_priority = 1 if item.source_type == "memory" else 0
    return (-item.relevance_score, -source_priority, item.source_ref)


def presentation_key(item: ContextItem) -> tuple[int, float, str, str]:
    """Present memory first by score, then conversation history chronologically."""
    source_group = 0 if item.source_type == "memory" else 1
    if source_group == 0:
        return (0, -item.relevance_score, item.created_at.isoformat() if item.created_at else "", item.source_ref)
    return (1, 0.0, item.created_at.isoformat() if item.created_at else "", item.source_ref)
