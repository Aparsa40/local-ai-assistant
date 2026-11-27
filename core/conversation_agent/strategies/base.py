"""Shared normalized execution contracts for online and offline strategies."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.conversation_agent.contracts import DestinationClass, ExecutionBudget, ExecutionStatus


class ExecutionAborted(Exception):
    """Raised inside a strategy when cancellation was requested between chunks."""


@dataclass(frozen=True)
class ExecutionRequest:
    """The same normalized input every strategy accepts; no SDK types enter here."""

    request_id: str
    messages: tuple[dict, ...]
    provider_id: str
    model: str
    destination_class: DestinationClass
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)


@dataclass(frozen=True)
class ExecutionResult:
    """The same normalized outcome every strategy returns; CANCELLED is not FAILED."""

    status: ExecutionStatus
    content: str = ""
    provider_id: str | None = None
    model_used: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status in {ExecutionStatus.FAILED, ExecutionStatus.UNAVAILABLE, ExecutionStatus.CANCELLED} and not self.error_code:
            raise ValueError("a failed, unavailable or cancelled result requires an error code")
