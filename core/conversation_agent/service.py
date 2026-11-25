"""Conversation Agent service: one auditable user-turn lifecycle (WP-8.2 to 8.6).

The service owns intake, deterministic dispatch, authorization-aware context
assembly, strategy execution, validation, composition, persistence and the
versioned SSE event stream. It reuses ConversationService, ContextManager,
PermissionManager, InterfaceManager and the Phase 7 OrchestrationService; it
never calls provider SDKs and never loops back to the application's own HTTP
endpoints.
"""
from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

from core.context.schemas import ContextRequest
from core.conversation_agent.contracts import (
    ConversationEvent,
    ConversationRequest,
    DestinationClass,
    DispatchDecision,
    ExecutionMode,
    ExecutionStatus,
    Provenance,
    ResponseCandidate,
    Route,
    ValidationReport,
    ValidationState,
    new_request_id,
    redact_payload,
)
from core.conversation_agent.dispatcher import DeterministicDispatcher
from core.conversation_agent.egress import authorize_transmission, classify_destination, partition_context
from core.conversation_agent.operations import ConversationOperation, OperationRegistry
from core.conversation_agent.strategies.base import ExecutionRequest
from core.conversation_agent.validator import ResponseValidator
from core.conversation_agent.composer import ResponseComposer

_TERMINAL_LANGUAGE = {
    "failed": "The execution failed and no answer was produced.",
    "cancelled": "The request was cancelled before completion.",
    "blocked": "The request was blocked by policy before execution.",
    "unavailable": "No eligible execution path was available; nothing was fabricated.",
    "needs_input": "Your input is required before this request can proceed.",
}


@dataclass(frozen=True)
class TurnOutcome:
    candidate: ResponseCandidate
    context_refs: frozenset


def _owner_id(access) -> str:
    """Resolve the data owner from the trusted application access context."""
    scope = getattr(access, "scope", None)
    owner = getattr(scope, "owner_id", None)
    if isinstance(owner, str) and 0 < len(owner) <= 160:
        return owner
    # Compatibility for isolated unit fixtures; production requests always
    # receive AccessContext from the local API boundary.
    return "local-user"


def _system_prompt() -> str:
    from core.config_manager import ConfigManager

    try:
        config = ConfigManager.load_config() or {}
        name = str(config.get("assistant_name", "Assistant"))
        prompt = str(config.get("system_prompt", ""))
        return "\u0646\u0627\u0645 \u062a\u0648 " + name + " \u0627\u0633\u062a. " + prompt
    except Exception:
        return "Assistant."


def _always_unready(provider_id, model) -> bool:
    return False


class ConversationAgentService:
    """Host the user-facing conversation workflow on the existing runtime stack."""

    def __init__(
        self,
        *,
        interface_manager,
        conversation_builder: Callable,
        context_builder: Callable,
        session_factory: Callable[[], object],
        orchestration_gateway=None,
        dispatcher: DeterministicDispatcher | None = None,
        validator: ResponseValidator | None = None,
        composer: ResponseComposer | None = None,
        registry: OperationRegistry | None = None,
        readiness_probe=None,
        fallback_order: tuple[str, ...] = (),
    ) -> None:
        self._interface_manager = interface_manager
        self._conversation_builder = conversation_builder
        self._context_builder = context_builder
        self._session_factory = session_factory
        self._orchestration_gateway = orchestration_gateway
        self._dispatcher = dispatcher or DeterministicDispatcher()
        self._validator = validator or ResponseValidator()
        self._composer = composer or ResponseComposer()
        self._registry = registry or OperationRegistry()
        self._readiness_probe = readiness_probe or _always_unready
        self._fallback_order = tuple(fallback_order)

    @property
    def registry(self) -> OperationRegistry:
        return self._registry

    def _event(self, operation: ConversationOperation, event_type: str, payload: dict) -> ConversationEvent:
        return ConversationEvent(
            event_id="evt_" + secrets.token_hex(8),
            request_id=operation.request_id,
            conversation_id=operation.session_id,
            type=event_type,
            payload=redact_payload(payload),
        )

    @staticmethod
    def _accepted_event(operation: ConversationOperation) -> ConversationEvent:
        return ConversationEvent(
            event_id="evt_" + secrets.token_hex(8),
            request_id=operation.request_id,
            conversation_id=operation.session_id,
            type="accepted",
            payload=redact_payload({"mode": "conversation-agent", "status": "running"}),
        )

    def _reject(self, payload: dict, code: str, safe_message: str) -> str:
        event = ConversationEvent(
            event_id="evt_" + secrets.token_hex(8),
            request_id=str(payload.get("request_id") or new_request_id())[:64],
            conversation_id=int(payload.get("session_id") or 0),
            type="error",
            payload=redact_payload({"error_code": code, "message": safe_message}),
        )
        return event.to_sse()

    async def stream(self, db, access, permission_manager, payload: dict) -> AsyncIterator[str]:
        """HTTP entry point: validate, reconcile, then stream the lifecycle."""
        from core.permissions.types import PermissionOperation

        session_id = payload.get("session_id")
        try:
            request = ConversationRequest.from_payload(payload, session_id=session_id)
        except (ValueError, TypeError) as exc:
            yield self._reject(payload, "invalid_request", self._safe_message(exc))
            return

        conversation_service = self._conversation_builder(db, access, permission_manager)
        try:
            # Session existence and permission are enforced before any
            # idempotency reconciliation, so foreign sessions cannot observe
            # or join another conversation's operation.
            conversation_service._authorize(request.session_id, PermissionOperation.UPDATE)
        except LookupError:
            yield self._reject(payload, "session_not_found", "The conversation session was not found.")
            return

        trusted_owner = _owner_id(access)
        if any(scope.owner_id != trusted_owner for scope in request.memory_scopes + request.knowledge_scopes):
            yield self._reject(payload, "scope_owner_mismatch", "A requested data scope does not belong to the authenticated local owner.")
            return

        operation, created = self._registry.start(request.session_id, request.request_id, request.message)
        yield self._accepted_event(operation).to_sse()
        if not created:
            # Duplicate submission: replay the recorded lifecycle; either the
            # terminal event or the live follow-on stream. No side effects run.
            async for event in self._registry.follow(operation, from_index=0):
                if event.type == "accepted" and not operation.is_terminal:
                    continue
                yield event.to_sse()
            return

        await operation.publish(self._accepted_event(operation))
        leader = asyncio.ensure_future(
            self._run_lifecycle(operation, request, access, permission_manager)
        )
        operation.leader_task = leader
        seen_accepted = False
        async for event in self._registry.follow(operation, from_index=0):
            if not seen_accepted and event.type == "accepted":
                seen_accepted = True
                continue
            yield event.to_sse()

    @staticmethod
    def _safe_message(exc: Exception) -> str:
        text = str(exc)
        if 0 < len(text) <= 300 and all(ch.isprintable() for ch in text):
            return text
        return "The request payload was rejected."

    async def _run_lifecycle(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        access,
        permission_manager,
    ) -> None:
        try:
            await self._execute_turn(operation, request, access, permission_manager)
        except asyncio.CancelledError:
            if operation.is_terminal:
                return
            await operation.publish(self._event(operation, "cancelled", {
                "status": "cancelled",
                "message": "The request was cancelled before completion.",
            }))
            raise
        except Exception:
            if operation.is_terminal:
                return
            await operation.publish(self._event(operation, "error", {
                "status": "failed",
                "error_code": "internal_error",
                "message": "The request failed before completion.",
            }))

    def _abort_check(self, operation: ConversationOperation) -> Callable[[], bool]:
        return lambda: operation.cancel_requested

    async def _execute_turn(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        access,
        permission_manager,
    ) -> None:
        decision = self._dispatcher.dispatch(request)
        await operation.publish(self._event(operation, "status", {
            "status": "dispatched",
            "route": decision.route.value,
            "reason_codes": list(decision.reason_codes),
            "provider_id": decision.provider_id,
            "model": decision.model,
            "destination_class": decision.destination_class.value,
        }))

        if decision.route in {Route.BLOCKED, Route.NEEDS_USER_INPUT, Route.DETERMINISTIC_WORKFLOW}:
            if decision.route is Route.NEEDS_USER_INPUT:
                final = {"status": "needs_input", "content": _TERMINAL_LANGUAGE["needs_input"],
                         "reason_codes": list(decision.reason_codes)}
            else:
                reason_codes = list(decision.reason_codes)
                if decision.route is Route.DETERMINISTIC_WORKFLOW:
                    reason_codes.append("workflow_runner_unregistered")
                final = {"status": "blocked", "content": _TERMINAL_LANGUAGE["blocked"],
                         "reason_codes": reason_codes}
            await operation.publish(self._event(operation, "final", final))
            return

        # Persist the user turn exactly once, before inference.
        with self._session_factory() as db:
            conversation_service = self._conversation_builder(db, access, permission_manager)
            try:
                conversation_service.prepare_chat(request.session_id, request.message)
            except LookupError:
                await operation.publish(self._event(operation, "error", {
                    "status": "failed",
                    "error_code": "session_not_found",
                    "message": "The conversation session was not found.",
                }))
                return
            context_manager = self._context_builder(conversation_service, db)

        try:
            outcome = await asyncio.wait_for(
                self._produce_candidate(
                    operation, request, decision, conversation_service, context_manager, access
                ),
                timeout=request.budget.wall_clock_seconds,
            )
        except asyncio.TimeoutError:
            outcome = None
            await operation.publish(self._event(operation, "final", {
                "status": "unavailable",
                "content": "The execution budget expired before completion; nothing was fabricated.",
                "reason_codes": ["budget_exceeded"],
            }))
            return
        if outcome is None:
            return
        candidate = outcome.candidate

        report = self._validator.validate(candidate, context_refs=outcome.context_refs)
        await operation.publish(self._event(operation, "validation", {
            "status": "validated",
            "state": report.state.value,
            "issues": [issue.code for issue in report.issues],
        }))

        if candidate.status is ExecutionStatus.CANCELLED:
            await operation.publish(self._event(operation, "cancelled", {
                "status": "cancelled",
                "message": "The request was cancelled before completion.",
                "provenance": Provenance(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    route=decision.route.value,
                    mode=candidate.mode.value,
                    provider_id=candidate.provider_id,
                    model_used=candidate.model_used,
                    execution_status="cancelled",
                ).to_dict(),
            }))
            return

        reason_text = None
        if report.state is ValidationState.REJECTED:
            reason_text = _TERMINAL_LANGUAGE.get(candidate.status.value)
        final_content, final_status = self._composer.compose(candidate, report, reason_text=reason_text)

        provenance = Provenance(
            session_id=request.session_id,
            request_id=request.request_id,
            route=decision.route.value,
            mode=candidate.mode.value,
            provider_id=candidate.provider_id,
            model_used=candidate.model_used,
            fallback_applied=candidate.fallback_applied,
            fallback_reason=candidate.fallback_reason,
            execution_status=candidate.status.value,
            orchestration_goal_id=candidate.goal_id,
            orchestration_plan_id=candidate.plan_id,
            source_refs=candidate.source_refs,
            error_code=candidate.error_code,
        )
        if candidate.status in {ExecutionStatus.COMPLETED, ExecutionStatus.PARTIAL}:
            with self._session_factory() as db:
                service = self._conversation_builder(db, access, permission_manager)
                service.append_assistant_message(
                    request.session_id, final_content, candidate.model_used or decision.model or "unknown",
                )
        await operation.publish(self._event(operation, "final", {
            "status": candidate.status.value,
            "content": final_content,
            "validation_state": report.state.value,
            "provenance": provenance.to_dict(),
        }))

    async def _produce_candidate(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        decision: DispatchDecision,
        conversation_service,
        context_manager,
        access,
    ) -> Optional[TurnOutcome]:
        if decision.route is Route.AGENT_DELEGATION:
            return await self._delegate(operation, request, decision)
        return await self._respond(operation, request, decision, context_manager, access)

    async def _respond(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        decision: DispatchDecision,
        context_manager,
        access,
    ) -> Optional[TurnOutcome]:
        from core.knowledge import KnowledgeScope
        from core.memory.types import MemoryScope
        from core.conversation_agent.strategies.online import OnlineStrategy
        from core.conversation_agent.strategies.offline import OfflineStrategy

        memory_scopes = tuple(
            MemoryScope(scope.scope_type, scope.scope_id, scope.owner_id)
            for scope in request.memory_scopes
        )
        knowledge_scopes = tuple(
            KnowledgeScope(scope.scope_type, scope.scope_id, scope.owner_id)
            for scope in request.knowledge_scopes
        )
        try:
            package = context_manager.assemble(
                ContextRequest(
                    conversation_id=request.session_id,
                    query=request.message,
                    owner_id=_owner_id(access),
                    history_limit=request.history_limit,
                    memory_scopes=memory_scopes,
                    knowledge_scopes=knowledge_scopes,
                )
            )
        except Exception:
            await operation.publish(self._event(operation, "error", {
                "status": "failed",
                "error_code": "context_assembly_failed",
                "message": "Authorized context could not be assembled.",
            }))
            return None

        all_refs = frozenset(
            getattr(item, "source_ref", "") for item in package.items if getattr(item, "source_ref", "")
        )
        destination = classify_destination(decision.provider_id)
        has_private = any(getattr(item, "source_type", "") in {"memory", "knowledge"} for item in package.items)
        egress = authorize_transmission(
            decision.provider_id,
            includes_private_context=has_private,
            user_authorized_private_context=request.authorize_private_context_egress,
        )
        transmissible, excluded = partition_context(
            package.items, destination, request.authorize_private_context_egress
        )
        if excluded:
            await operation.publish(self._event(operation, "status", {
                "status": "context_filtered",
                "reason_codes": ["private_context_excluded"],
                "detail": "Private local context was not transmitted to the cloud destination.",
            }))
        if not egress.allowed and not transmissible:
            await operation.publish(self._event(operation, "final", {
                "status": "blocked",
                "content": _TERMINAL_LANGUAGE["blocked"],
                "reason_codes": ["private_context_egress_denied"],
            }))
            return None

        mode = (
            ExecutionMode.OFFLINE if destination is DestinationClass.LOCAL else ExecutionMode.ONLINE
        )
        await operation.publish(self._event(operation, "progress", {"status": "context_ready", "mode": mode.value}))

        messages = [{"role": "system", "content": _system_prompt()}]
        for item in transmissible:
            if getattr(item, "source_type", "") == "conversation":
                messages.append({"role": item.role or "user", "content": item.content})
        # Private local context is transmitted only when it survived
        # partitioning, which already required explicit user authorization for
        # cloud destinations.
        for item in transmissible:
            if getattr(item, "source_type", "") in {"memory", "knowledge"}:
                messages.append({"role": "system", "content": item.content})
        messages.append({"role": "user", "content": request.message})

        def build_execution_request(provider_id: str, destination_class: DestinationClass) -> ExecutionRequest:
            return ExecutionRequest(
                request_id=request.request_id,
                messages=tuple(messages),
                provider_id=provider_id,
                model=decision.model or "",
                destination_class=destination_class,
                budget=request.budget,
            )

        abort_check = self._abort_check(operation)
        if destination is DestinationClass.LOCAL:
            strategy = OfflineStrategy(self._interface_manager, self._readiness_probe)
            result = await strategy.execute(build_execution_request(decision.provider_id, destination), abort_check=abort_check)
        else:
            strategy = OnlineStrategy(self._interface_manager)
            result = await strategy.execute(build_execution_request(decision.provider_id, destination), abort_check=abort_check)

        # Deterministic, disclosed fallback: a local destination that is not
        # ready may fall back to an explicitly configured eligible cloud
        # provider; private context is stripped unless egress was authorized.
        limitations: list[str] = []
        fallback_applied = False
        fallback_reason = None
        if result.status is ExecutionStatus.UNAVAILABLE and destination is DestinationClass.LOCAL:
            cloud_fallback = next(
                (pid for pid in self._fallback_order if classify_destination(pid) is DestinationClass.CLOUD),
                None,
            )
            if cloud_fallback:
                cloud_egress = authorize_transmission(
                    cloud_fallback,
                    includes_private_context=has_private,
                    user_authorized_private_context=request.authorize_private_context_egress,
                )
                if cloud_egress.allowed:
                    cloud_result = await OnlineStrategy(self._interface_manager).execute(
                        build_execution_request(cloud_fallback, DestinationClass.CLOUD),
                        abort_check=abort_check,
                    )
                    if cloud_result.status is ExecutionStatus.COMPLETED or (
                        cloud_result.status is ExecutionStatus.CANCELLED and abort_check()
                    ):
                        fallback_applied = True
                        fallback_reason = (
                            "the selected local provider was not ready; execution used the "
                            "authorized cloud provider " + cloud_fallback +
                            ("; private context was excluded" if excluded else "")
                        )
                        result = cloud_result
                        mode = ExecutionMode.ONLINE
                else:
                    limitations.append(
                        "The local provider was not ready and the cloud fallback is not authorized for the requested context."
                    )

        if result.status is ExecutionStatus.UNAVAILABLE:
            limitations.append("The selected provider was not available; no authorized fallback existed.")
            return TurnOutcome(
                ResponseCandidate(
                    content="",
                    status=ExecutionStatus.UNAVAILABLE,
                    mode=mode,
                    provider_id=decision.provider_id,
                    model_used=decision.model,
                    fallback_applied=fallback_applied,
                    fallback_reason=fallback_reason,
                    source_refs=(),
                    limitations=tuple(limitations),
                    reason_codes=tuple(decision.reason_codes),
                    error_code=result.error_code,
                ),
                all_refs,
            )
        if result.status is ExecutionStatus.CANCELLED:
            return TurnOutcome(
                ResponseCandidate(
                    content="",
                    status=ExecutionStatus.CANCELLED,
                    mode=mode,
                    provider_id=decision.provider_id,
                    model_used=decision.model,
                    error_code=result.error_code,
                ),
                all_refs,
            )
        if result.status is ExecutionStatus.FAILED:
            return TurnOutcome(
                ResponseCandidate(
                    content="",
                    status=ExecutionStatus.FAILED,
                    mode=mode,
                    provider_id=decision.provider_id,
                    model_used=decision.model,
                    fallback_applied=fallback_applied,
                    fallback_reason=fallback_reason,
                    source_refs=(),
                    reason_codes=tuple(decision.reason_codes),
                    error_code=result.error_code,
                ),
                all_refs,
            )

        truncated = "[output truncated at the execution budget]" in result.content
        status = ExecutionStatus.PARTIAL if (truncated or fallback_applied) else ExecutionStatus.COMPLETED
        if truncated:
            limitations.append("The response was truncated at the execution output budget.")
        return TurnOutcome(
            ResponseCandidate(
                content=result.content,
                status=status,
                mode=mode,
                provider_id=result.provider_id,
                model_used=result.model_used,
                fallback_applied=fallback_applied,
                fallback_reason=fallback_reason,
                source_refs=tuple(
                    getattr(item, "source_ref", "") for item in transmissible if getattr(item, "source_ref", "")
                )[:100],
                limitations=tuple(limitations),
                reason_codes=tuple(decision.reason_codes),
            ),
            all_refs,
        )

    async def _delegate(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        decision: DispatchDecision,
    ) -> Optional[TurnOutcome]:
        if self._orchestration_gateway is None:
            await operation.publish(self._event(operation, "final", {
                "status": "blocked",
                "content": _TERMINAL_LANGUAGE["blocked"],
                "reason_codes": ["delegation_unavailable"],
            }))
            return None
        await operation.publish(self._event(operation, "progress", {
            "status": "delegating",
            "detail": "A bounded goal was submitted to the orchestration service.",
        }))
        outcome = await self._orchestration_gateway.delegate(
            request,
            authorized_scopes=tuple(request.memory_scopes) + tuple(request.knowledge_scopes),
        )
        await operation.publish(self._event(operation, "progress", {
            "status": "delegation_finished",
            "goal_id": outcome.goal_id,
            "plan_id": outcome.plan_id,
        }))
        return TurnOutcome(
            ResponseCandidate(
                content=outcome.content,
                status=outcome.status,
                mode=ExecutionMode.DELEGATED,
                provider_id=decision.provider_id,
                model_used=decision.model,
                source_refs=(),
                limitations=outcome.limitations,
                reason_codes=tuple(decision.reason_codes),
                goal_id=outcome.goal_id,
                plan_id=outcome.plan_id,
                node_outcomes=tuple(dict(node) for node in outcome.node_outcomes),
                error_code=outcome.error_code,
            ),
            frozenset(),
        )
