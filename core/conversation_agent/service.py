"""Conversation Agent service: one auditable user-turn lifecycle (WP-8.2 to 8.6).

The service owns intake, deterministic dispatch, authorization-aware context
assembly, strategy execution, validation, composition, persistence and the
versioned SSE event stream. It reuses ConversationService, ContextManager,
PermissionManager, InterfaceManager and the Phase 7 OrchestrationService; it
never calls provider SDKs or the application's own HTTP endpoints.
"""
from __future__ import annotations

import asyncio
import secrets
from typing import AsyncIterator, Callable, Optional

from core.context.manager import ContextManager
from core.context.schemas import ContextRequest
from core.conversation_agent.contracts import (
    ConversationEvent,
    ConversationRequest,
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

SAFE_EVENT_TYPES = frozenset({
    "accepted", "status", "progress", "candidate", "validation",
    "approval_required", "final", "error", "cancelled",
})

_TERMINAL_LANGUAGE = {
    "failed": "The execution failed and no answer was produced.",
    "cancelled": "The request was cancelled before completion.",
    "blocked": "The request was blocked by policy before execution.",
    "unavailable": "No eligible execution path was available; nothing was fabricated.",
    "needs_input": "Your input is required before this request can proceed.",
    "partial": "Only part of the requested work completed; see limitations.",
}


class ConversationAgentService:
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
        self._readiness_probe = readiness_probe
        self._fallback_order = tuple(fallback_order)

    @property
    def registry(self) -> OperationRegistry:
        return self._registry

    def event(self, operation: ConversationOperation, event_type: str, payload: dict) -> ConversationEvent:
        return ConversationEvent(
            event_id="evt_" + secrets.token_hex(8),
            request_id=operation.request_id,
            conversation_id=operation.session_id,
            type=event_type,
            payload=redact_payload(payload),
        )

    async def stream(self, db, access, permission_manager, payload: dict) -> AsyncIterator[str]:
        """HTTP entry point: validate, reconcile, then stream the lifecycle."""
        session_id = payload.get("session_id")
        try:
            request = ConversationRequest.from_payload(payload, session_id=session_id)
        except ValueError as exc:
            # Rejected before any persistence or inference.
            error_event = ConversationEvent(
                event_id="evt_" + secrets.token_hex(8),
                request_id=str(payload.get("request_id") or new_request_id()),
                conversation_id=int(session_id or 0),
                type="error",
                payload=redact_payload({"error_code": "invalid_request", "message": str(exc)}),
            )
            yield error_event.to_sse()
            return

        conversation_service = self._conversation_builder(db, access, permission_manager)
        try:
            # Session existence/permission is enforced before idempotency returns
            # a reconciled result, so foreign sessions cannot observe operations.
            conversation_service._authorize(request.session_id, _require_update())
        except LookupError:
            pass

        operation, created = self._registry.start(
            request.session_id, request.request_id, request.message
        )
        if not created:
            if operation.is_terminal and operation.terminal is not None:
                yield self._accepted_event(operation).to_sse()
                yield operation.terminal.to_sse()
            else:
                # Duplicate submission while running: replay, then follow live.
                yield self._accepted_event(operation).to_sse()
                async for event in self._registry.follow(operation, from_index=0):
                    if event.type == "accepted":
                        continue
                    yield event.to_sse()
            return

        await operation.publish(self._accepted_event(operation))
        leader = asyncio.ensure_future(
            self._run_lifecycle(operation, request, access, permission_manager)
        )
        operation.leader_task = leader
        first = True
        async for event in self._registry.follow(operation, from_index=0):
            if first and event.type == "accepted":
                first = False
                continue
            first = False
            yield event.to_sse()
        try:
            await leader
        except asyncio.CancelledError:
            raise

    def _accepted_event(self, operation: ConversationOperation) -> ConversationEvent:
        return ConversationEvent(
            event_id="evt_" + secrets.token_hex(8),
            request_id=operation.request_id,
            conversation_id=operation.session_id,
            type="accepted",
            payload=redact_payload({"mode": "conversation-agent", "status": "running"}),
        )

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
            await operation.publish(self.event(operation, "cancelled", {
                "status": "cancelled",
                "message": "The request was cancelled before completion.",
            }))
            raise
        except Exception:
            if operation.is_terminal:
                return
            await operation.publish(self.event(operation, "error", {
                "status": "failed",
                "error_code": "internal_error",
                "message": "The request failed before completion.",
            }))

    async def _execute_turn(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        access,
        permission_manager,
    ) -> None:
        decision = self._dispatcher.dispatch(request)
        await operation.publish(self.event(operation, "status", {
            "status": "dispatched",
            "route": decision.route.value,
            "reason_codes": list(decision.reason_codes),
            "provider_id": decision.provider_id,
            "model": decision.model,
            "destination_class": decision.destination_class.value,
        }))

        if decision.route is Route.BLOCKED:
            await operation.publish(self.event(operation, "final", {
                "status": "blocked",
                "content": _TERMINAL_LANGUAGE["blocked"],
                "reason_codes": list(decision.reason_codes),
            }))
            return
        if decision.route is Route.NEEDS_USER_INPUT:
            await operation.publish(self.event(operation, "final", {
                "status": "needs_input",
                "content": _TERMINAL_LANGUAGE["needs_input"],
                "reason_codes": list(decision.reason_codes),
            }))
            return
        if decision.route is Route.DETERMINISTIC_WORKFLOW:
            await operation.publish(self.event(operation, "final", {
                "status": "blocked",
                "content": _TERMINAL_LANGUAGE["blocked"],
                "reason_codes": list(decision.reason_codes) + ["workflow_runner_unregistered"],
            }))
            return

        # Persist the user turn exactly once, before inference.
        with self._session_factory() as db:
            conversation_service = self._conversation_builder(db, access, permission_manager)
            try:
                conversation_service.prepare_chat(request.session_id, request.message)
            except LookupError:
                await operation.publish(self.event(operation, "error", {
                    "status": "failed",
                    "error_code": "session_not_found",
                    "message": "The conversation session was not found.",
                }))
                return
            context_manager = self._context_builder(conversation_service, db)

        candidate = await self._produce_candidate(
            operation, request, decision, conversation_service, context_manager
        )
        if candidate is None:
            return

        report = self._validator.validate(candidate, context_refs=frozenset())
        await operation.publish(self.event(operation, "validation", {
            "status": "validated",
            "state": report.state.value,
            "issues": [issue.code for issue in report.issues],
        }))

        final_content, final_status = _compose_final(
            self._composer, candidate, report
        )
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
            source_refs=candidate.source_refs[:100],
            error_code=candidate.error_code,
        )
        if candidate.status in {ExecutionStatus.COMPLETED, ExecutionStatus.PARTIAL}:
            with self._session_factory() as db:
                service = self._conversation_builder(db, access, permission_manager)
                service.append_assistant_message(request.session_id, final_content, candidate.model_used or decision.provider_id or "unknown")
        await operation.publish(self.event(operation, "final", {
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
        context_manager: ContextManager,
    ) -> Optional[ResponseCandidate]:
        if decision.route is Route.AGENT_DELEGATION:
            return await self._delegate(operation, request, decision, conversation_service)
        return await self._respond(operation, request, decision, conversation_service, context_manager)

    async def _respond(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        decision: DispatchDecision,
        conversation_service,
        context_manager: ContextManager,
    ) -> Optional[ResponseCandidate]:
        from core.context.schemas import ContextRequest as _ContextRequest
        from core.knowledge import KnowledgeScope
        from core.memory.types import MemoryScope

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
                _ContextRequest(
                    conversation_id=request.session_id,
                    query=request.message,
                    owner_id=_owner_id(request, operation),
                    history_limit=request.history_limit,
                    memory_scopes=memory_scopes,
                    knowledge_scopes=knowledge_scopes,
                )
            )
        except Exception:
            await operation.publish(self.event(operation, "error", {
                "status": "failed",
                "error_code": "context_assembly_failed",
                "message": "Authorized context could not be assembled.",
            }))
            return None

        destination = classify_destination(decision.provider_id)
        egress = authorize_transmission(
            decision.provider_id,
            includes_private_context=bool(request.memory_scopes or request.knowledge_scopes)
            or any(getattr(item, "source_type", "") in {"memory", "knowledge"} for item in package.items),
            user_authorized_private_context=request.authorize_private_context_egress,
        )
        transmissible, excluded = partition_context(
            package.items, destination, request.authorize_private_context_egress
        )
        if excluded:
            await operation.publish(self.event(operation, "status", {
                "status": "context_filtered",
                "reason_codes": ["private_context_excluded"],
                "detail": "Private local context was not transmitted to the selected destination.",
            }))
        if not egress.allowed and not transmissible and (request.memory_scopes or request.knowledge_scopes):
            # The whole payload would be private context; fail closed.
            await operation.publish(self.event(operation, "final", {
                "status": "blocked",
                "content": _TERMINAL_LANGUAGE["blocked"],
                "reason_codes": ["private_context_egress_denied"],
            }))
            return None

        await operation.publish(self.event(operation, "progress", {
            "status": "context_ready",
            "mode": "online" if destination is destination.CLOUD else "offline",
        }))

        system_prompt = _system_prompt()
        messages = [{"role": "system", "content": system_prompt}]
        for item in transmissible:
            if getattr(item, "source_type", "") == "conversation":
                messages.append({"role": item.role or "user", "content": item.content})
        messages.append({"role": "user", "content": request.message})

        execution_request = ExecutionRequest(
            request_id=request.request_id,
            messages=tuple(messages),
            provider_id=decision.provider_id or "",
            model=decision.model or "",
            destination_class=destination,
            budget=request.budget,
        )
        from core.conversation_agent.strategies.selector import ExecutionSelector
        from core.conversation_agent.strategies.online import OnlineStrategy
        from core.conversation_agent.strategies.offline import OfflineStrategy

        if destination is destination.LOCAL:
            strategy = OfflineStrategy(self._interface_manager, self._readiness_probe or _always_unready)
        else:
            strategy = OnlineStrategy(self._interface_manager)
        result = await strategy.execute(execution_request)

        if result.status is ExecutionStatus.COMPLETED and not result.content.strip():
            result = _replace(result, status=ExecutionStatus.FAILED, error_code="empty_inference")

        fallback_applied = False
        fallback_reason = None
        if result.status is not ExecutionStatus.COMPLETED and destination is destination.LOCAL:
            cloud_fallback = next(
                (pid for pid in self._fallback_order if classify_destination(pid) is destination.CLOUD), None
            )
            if cloud_fallback:
                cloud_egress = authorize_transmission(
                    cloud_fallback,
                    includes_private_context=bool(request.memory_scopes or request.knowledge_scopes),
                    user_authorized_private_context=request.authorize_private_context_egress,
                )
                if cloud_egress.allowed or not (request.memory_scopes or request.knowledge_scopes):
                    filtered, _ = partition_context(
                        package.items, destination.CLOUD, request.authorize_private_context_egress
                    )
                    retry_messages = [dict(message) for message in messages]
                    if len(filtered) != len(transmissible):
                        fallback_reason = "local runtime was not ready; private context was excluded from the cloud fallback"
                    else:
                        fallback_reason = "the selected local provider was not ready"
                    fallback_applied = True
                    from core.conversation_agent.strategies.online import OnlineStrategy as _Online
                    cloud_result = await _Online(self._interface_manager).execute(
                        ExecutionRequest(
                            request_id=request.request_id,
                            messages=tuple(retry_messages),
                            provider_id=cloud_fallback,
                            model=decision.model or "",
                            destination_class=destination.CLOUD,
                            budget=request.budget,
                        )
                    )
                    if cloud_result.status is ExecutionStatus.COMPLETED:
                        return ResponseCandidate(
                            content=cloud_result.content,
                            status=ExecutionStatus.PARTIAL,
                            mode=ExecutionMode.ONLINE,
                            provider_id=cloud_result.provider_id,
                            model_used=cloud_result.model_used,
                            fallback_applied=True,
                            fallback_reason=fallback_reason,
                            source_refs=tuple(
                                getattr(item, "source_ref", "") for item in transmissible
                                if getattr(item, "source_ref", "")
                            ),
                            limitations=(),
                            reason_codes=("fallback_from_local",),
                        )

        content = result.content if result.status in {ExecutionStatus.COMPLETED, ExecutionStatus.PARTIAL} else ""
        limitations: list[str] = []
        if result.status is ExecutionStatus.UNAVAILABLE:
            limitations.append("The selected provider was not available; no fallback was authorized.")
        return ResponseCandidate(
            content=content,
            status=(ExecutionStatus.PARTIAL if "[output truncated" in content else result.status),
            mode=ExecutionMode.OFFLINE if destination is destination.LOCAL else ExecutionMode.ONLINE,
            provider_id=result.provider_id or decision.provider_id,
            model_used=result.model_used or decision.model,
            fallback_applied=fallback_applied,
            fallback_reason=fallback_reason,
            source_refs=tuple(
                getattr(item, "source_ref", "") for item in transmissible
                if getattr(item, "source_ref", "")
            ),
            limitations=tuple(limitations),
            reason_codes=tuple(decision.reason_codes),
            error_code=result.error_code,
        )

    async def _delegate(
        self,
        operation: ConversationOperation,
        request: ConversationRequest,
        decision: DispatchDecision,
        conversation_service,
    ) -> Optional[ResponseCandidate]:
        if self._orchestration_gateway is None:
            await operation.publish(self.event(operation, "final", {
                "status": "blocked",
                "content": _TERMINAL_LANGUAGE["blocked"],
                "reason_codes": ["delegation_unavailable"],
            }))
            return None
        authorized = tuple(request.memory_scopes) + tuple(request.knowledge_scopes)
        await operation.publish(self.event(operation, "progress", {
            "status": "delegating",
            "detail": "A bounded goal was submitted to the orchestration service.",
        }))
        outcome = await self._orchestration_gateway.delegate(request, authorized_scopes=authorized)
        await operation.publish(self.event(operation, "progress", {
            "status": "delegation_finished",
            "goal_id": outcome.goal_id,
            "plan_id": outcome.plan_id,
        }))
        return ResponseCandidate(
            content=outcome.content or "",
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
        )


def _require_update():
    from core.permissions.types import PermissionOperation

    return PermissionOperation.UPDATE


def _owner_id(request: ConversationRequest, operation: ConversationOperation) -> str:
    metadata = request.client_metadata or {}
    owner = metadata.get("owner_id")
    if isinstance(owner, str) and owner and len(owner) <= 160:
        return owner
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



def _always_unready(provider_id, model):
    return False


def _replace(result, **changes):
    from dataclasses import replace

    return replace(result, **changes)


def _compose_final(composer, candidate, report):
    reason_text = None
    if report.state is ValidationState.REJECTED:
        reason_text = _TERMINAL_LANGUAGE.get(candidate.status.value)
    return composer.compose(candidate, report, reason_text=reason_text)
