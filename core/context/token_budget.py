"""Deterministic conservative token-budget estimation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenBudgetPolicy:
    """Character-based estimate; deliberately avoids model-specific tokenizers."""

    characters_per_token: int = 3
    item_overhead_tokens: int = 12

    def __post_init__(self) -> None:
        if isinstance(self.characters_per_token, bool) or not isinstance(self.characters_per_token, int) or self.characters_per_token < 1:
            raise ValueError("characters_per_token must be a positive integer")
        if isinstance(self.item_overhead_tokens, bool) or not isinstance(self.item_overhead_tokens, int) or self.item_overhead_tokens < 0:
            raise ValueError("item_overhead_tokens must be a non-negative integer")

    def estimate(self, content: str) -> int:
        if not content:
            return self.item_overhead_tokens
        return (len(content) + self.characters_per_token - 1) // self.characters_per_token + self.item_overhead_tokens
