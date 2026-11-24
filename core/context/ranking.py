"""Stable cross-source ranking helpers for context candidates."""

from __future__ import annotations

from datetime import datetime

from .schemas import ContextItem


def conversation_recency_score(index: int, total: int) -> float:
    """Score chronological history so newer messages are considered first."""
    if total <= 0:
        return 0.0
    return 0.55 + 0.45 * ((index + 1) / total)


def selection_key(item: ContextItem) -> tuple[float, int, float, str]:
    """Higher relevance first; memory wins exact ties; stable source ordering follows."""
    timestamp = item.created_at.timestamp() if isinstance(item.created_at, datetime) else 0.0
    source_priority = 1 if item.source_type == "memory" else 0
    return (-item.relevance_score, -source_priority, -timestamp, item.source_ref)


def presentation_key(item: ContextItem) -> tuple[int, float, float, str]:
    """Present approved memory first, then conversation history chronologically."""
    source_group = 0 if item.source_type == "memory" else 1
    timestamp = item.created_at.timestamp() if isinstance(item.created_at, datetime) else 0.0
    return (source_group, -item.relevance_score if source_group == 0 else timestamp, timestamp, item.source_ref)
