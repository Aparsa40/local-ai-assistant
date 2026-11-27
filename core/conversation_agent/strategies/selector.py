"""Choose the eligible strategy and re-check policy on fallback (WP-8.3)."""
from __future__ import annotations

from core.conversation_agent.contracts import DestinationClass
from ..egress import classify_destination
from .base import ExecutionRequest, ExecutionResult
from .offline import OfflineStrategy
from .online import OnlineStrategy


class ExecutionSelector:
    """Run the preferred strategy; on failure, re-check every fallback candidate."""

    def __init__(self, interface_manager, *, readiness_probe, fallback_order: tuple[str, ...] = ()) -> None:
        self._interface_manager = interface_manager
        self._online = OnlineStrategy(interface_manager)
        self._offline = OfflineStrategy(interface_manager, readiness_probe)
        self._fallback_order = fallback_order

    async def execute(self, provider_id: str, base_request: ExecutionRequest) -> ExecutionResult:
        result = await self._run_one(provider_id, base_request)
        if result.status is ExecutionStatus.COMPLETED:
            return result
        # Deterministic fallback: re-check destination policy and capability for
        # every candidate; never silently select an unauthorized destination.
        for candidate_provider in self._fallback_order:
            if candidate_provider == provider_id or not candidate_provider:
                continue
            if classify_destination(candidate_provider) is DestinationClass.CLOUD and classify_destination(provider_id) is DestinationClass.CLOUD:
                # Never silently move private context between cloud destinations.
                continue
            retry = await self._run_one(candidate_provider, base_request)
            if retry.status is ExecutionStatus.COMPLETED:
                return retry
        return result

    async def _run_one(self, provider_id: str, base_request: ExecutionRequest) -> ExecutionResult:
        if classify_destination(provider_id) is DestinationClass.LOCAL:
            return await self._offline.execute(
                ExecutionRequest(
                    request_id=base_request.request_id,
                    messages=base_request.messages,
                    provider_id=provider_id,
                    model=base_request.model,
                    destination_class=DestinationClass.LOCAL,
                    budget=base_request.budget,
                )
            )
        return await self._online.execute(
            ExecutionRequest(
                request_id=base_request.request_id,
                messages=base_request.messages,
                provider_id=provider_id,
                model=base_request.model,
                destination_class=DestinationClass.CLOUD,
                budget=base_request.budget,
            )
        )


def select_execution_strategy(interface_manager, *, readiness_probe, fallback_order=()) -> ExecutionSelector:
    return ExecutionSelector(interface_manager, readiness_probe=readiness_probe, fallback_order=tuple(fallback_order))
