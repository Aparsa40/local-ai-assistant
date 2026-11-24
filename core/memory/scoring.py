"""Deterministic metadata-first memory relevance scoring."""
from __future__ import annotations

import re
from datetime import datetime, timezone


def terms(value: str) -> set[str]:
    return {item.casefold() for item in re.findall(r"[^\W_]+", value, flags=re.UNICODE) if len(item) > 1}


def score_memory(content: str, query: str, importance: int, confidence: int, updated_at: datetime, now: datetime) -> tuple[float, tuple[str, ...]]:
    query_terms = terms(query)
    content_terms = terms(content)
    matched = tuple(sorted(query_terms & content_terms))
    overlap = len(matched) / max(1, len(query_terms))
    age_days = max(0.0, (now - updated_at).total_seconds() / 86400)
    freshness = 1.0 / (1.0 + age_days / 30.0)
    score = (
        0.55 * overlap
        + 0.20 * (importance / 100)
        + 0.15 * (confidence / 100)
        + 0.10 * freshness
    )
    return round(score, 6), matched
