"""Local strategy: require evidenced local readiness before inference."""
from __future__ import annotations

from core.interface_manager import InterfaceManager

from ..contracts import ExecutionStatus
from .base import ExecutionRequest, ExecutionResult


class OfflineStrategy:
    """Execute on the local destination only when readiness is evidenced by the probe."""

    def __init__(self, interface_manager: InterfaceManager, readiness_probe) -> None:
        self._interface_manager = interface_manager
        self._readiness_probe = readiness_probe

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        try:
            ready = bool(await self._readiness_probe(request.provider_id, request.model))
        except Exception:
            ready = False
        if not ready:
            return ExecutionResult(
                status=ExecutionStatus.UNAVAILABLE,
                provider_id=request.provider_id,
                model_used=request.model,
                error_code="local_runtime_not_ready",
            )
        chunks: list[str] = []
        try:
            async for chunk in self._interface_manager.stream_chat(
                request.provider_id,
                [dict(message) for message in request.messages],
                model=request.model,
            ):
                if not isinstance(chunk, str):
                    continue
                chunks.append(chunk)
                if sum(len(item) for item in chunks) > request.budget.max_output_chars:
                    chunks.append("\n[output truncated at the execution budget]")
                    break
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
