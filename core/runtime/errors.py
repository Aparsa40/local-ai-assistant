"""Typed, secret-safe errors for local runtime operations."""
from __future__ import annotations


class RuntimeErrorBase(Exception):
    def __init__(
        self,
        category: str,
        message: str,
        runtime_id: str | None = None,
        model_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.safe_message = message
        self.runtime_id = runtime_id
        self.model_id = model_id
        self.retryable = retryable


class RuntimeNotRegisteredError(RuntimeErrorBase):
    def __init__(self, runtime_id: str) -> None:
        super().__init__("runtime_not_registered", "The requested runtime is not registered.", runtime_id)


class RuntimeCapabilityError(RuntimeErrorBase):
    def __init__(self, runtime_id: str, operation: str) -> None:
        super().__init__(
            "runtime_operation_unsupported",
            f"Runtime '{runtime_id}' does not support '{operation}'.",
            runtime_id,
        )


class RuntimeOperationError(RuntimeErrorBase):
    """Normalized adapter or lifecycle failure safe to expose to callers."""
