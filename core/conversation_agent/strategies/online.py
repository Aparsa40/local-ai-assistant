"""Cloud strategy: invoke a cloud destination through InterfaceManager only."""
from __future__ import annotations

from typing import Callable, Optional

from core.interface_manager import InterfaceManager

from ..contracts import ExecutionStatus
from .base import ExecutionAborted, ExecutionRequest, ExecutionResult


class OnlineStrategy:
    def __init__(self, interface_manager: InterfaceManager) -> None:
        self._interface_manager = interface_manager

    async def execute(self, request: ExecutionRequest, *, abort_check: Optional[Callable[[], bool]] = None) -> ExecutionResult:
        chunks: list[str] = []
        try:
            async for chunk in self._interface_manager.stream_chat(
                request.provider_id,
                [dict(message) for message in request.messages],
                model=request.model,
            ):
                if abort_check is not None and abort_check():
                    raise ExecutionAborted()
                if not isinstance(chunk, str):
                    continue
                chunks.append(chunk)
                if sum(len(item) for item in chunks) > request.budget.max_output_chars:
                    chunks.append("\n[output truncated at the execution budget]")
                    break
        except ExecutionAborted:
            return ExecutionResult(
                status=ExecutionStatus.CANCELLED,
                content="".join(chunks),
                provider_id=request.provider_id,
                model_used=request.model,
                error_code="cancelled",
            )
        except Exception:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                provider_id=request.provider_id,
                model_used=request.model,
                error_code="inference_failed",
            )
        return ExecutionResult(
            status=ExecutionStatus.COMPLETED,
            content="".join(chunks),
            provider_id=request.provider_id,
            model_used=request.model,
        )
