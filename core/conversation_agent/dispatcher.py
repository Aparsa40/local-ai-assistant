"""Deterministic, conservative dispatch for user turns (WP-8.2).

Rules are explicit and table-driven in tests. A model-assisted classifier is
advisory only: its output is schema-validated, cannot select delegation, cannot
grant permissions, and any malformed, timed-out or unavailable output falls
back to the deterministic decision.
"""
from __future__ import annotations

from core.config_manager import ConfigManager
from core.orchestrator import Orchestrator

from .contracts import ConversationRequest, DestinationClass, DispatchDecision, Route
from .egress import LOCAL_PROVIDER_IDS

DELEGATION_PREFIX = "!delegate "
WORKFLOW_PREFIX = "/workflow "

# Explicit, conservative workflows. Empty by design: deterministic application
# operations are only routed here when an owning service is registered.
DETERMINISTIC_WORKFLOWS: dict[str, str] = {}


class DeterministicDispatcher:
    """Classify one validated request into a closed Route using fixed rules."""

    def __init__(self, *, classifier=None, workflows=None, orchestration_available=True) -> None:
        self._classifier = classifier
        self._workflows = dict(DETERMINISTIC_WORKFLOWS if workflows is None else workflows)
        self._orchestration_available = orchestration_available

    def resolve_provider_selection(self, request: ConversationRequest) -> tuple[str | None, str | None]:
        """Resolve the user's selected provider/model without changing them."""
        provider_id = request.provider_id
        model = request.model
        if provider_id is None or model is None:
            try:
                orchestrator = Orchestrator()
                configured_provider = orchestrator.get_provider_id()
                configured_model = orchestrator.select_model(request.message)
            except Exception:
                return provider_id, model
            provider_id = provider_id or configured_provider
            model = model or configured_model or None
        return provider_id, model

    def dispatch(self, request: ConversationRequest) -> DispatchDecision:
        provider_id, model = self.resolve_provider_selection(request)
        if provider_id is None or not model:
            return DispatchDecision(
                route=Route.BLOCKED,
                reason_codes=("no_model_selected",),
                destination_class=DestinationClass.NONE,
                provider_id=provider_id,
                model=model,
            )

        destination = (
            DestinationClass.LOCAL if provider_id in LOCAL_PROVIDER_IDS else DestinationClass.CLOUD
        )

        message = request.message
        stripped = message.lstrip()

        if stripped.startswith(WORKFLOW_PREFIX):
            name = stripped[len(WORKFLOW_PREFIX):].split(" ", 1)[0].strip()
            if name in self._workflows:
                return DispatchDecision(
                    route=Route.DETERMINISTIC_WORKFLOW,
                    reason_codes=("registered_workflow", name),
                    destination_class=DestinationClass.NONE,
                    budget=request.budget,
                )
            return DispatchDecision(
                route=Route.NEEDS_USER_INPUT,
                reason_codes=("unknown_workflow",),
                destination_class=DestinationClass.NONE,
            )

        if request.force_delegation or stripped.startswith(DELEGATION_PREFIX):
            if not self._orchestration_available:
                return DispatchDecision(
                    route=Route.BLOCKED,
                    reason_codes=("delegation_unavailable",),
                    destination_class=DestinationClass.NONE,
                    provider_id=provider_id,
                    model=model,
                    budget=request.budget,
                )
            return DispatchDecision(
                route=Route.AGENT_DELEGATION,
                reason_codes=("explicit_delegation_request",),
                destination_class=destination,
                provider_id=provider_id,
                model=model,
                budget=request.budget,
            )

        # Advisory classification before the default decision: it may only
        # move an ordinary question to needs_user_input and back; every other
        # proposal is ignored and the deterministic rule stands.
        if self._classifier is not None:
            proposal = self._classifier.classify(request)
            if proposal is not None:
                route, reason = proposal
                if route in {Route.DIRECT_RESPONSE, Route.NEEDS_USER_INPUT}:
                    return DispatchDecision(
                        route=route,
                        reason_codes=(reason,),
                        destination_class=destination if route is Route.DIRECT_RESPONSE else DestinationClass.NONE,
                        provider_id=provider_id if route is Route.DIRECT_RESPONSE else None,
                        model=model if route is Route.DIRECT_RESPONSE else None,
                        budget=request.budget,
                    )

        return DispatchDecision(
            route=Route.DIRECT_RESPONSE,
            reason_codes=("ordinary_question",),
            destination_class=destination,
            provider_id=provider_id,
            model=model,
            budget=request.budget,
        )
