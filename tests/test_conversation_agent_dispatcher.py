import pytest

import core.config_manager as config_manager
from core.conversation_agent.contracts import ConversationRequest, Route
from core.conversation_agent.dispatcher import (
    DELEGATION_PREFIX,
    DETERMINISTIC_WORKFLOWS,
    WORKFLOW_PREFIX,
    DeterministicDispatcher,
)


@pytest.fixture(autouse=True)
def stable_config(monkeypatch):
    monkeypatch.setattr(
        config_manager.ConfigManager, "load_config",
        staticmethod(lambda: {
            "active_provider": "openrouter",
            "assistant_name": "assistant",
            "system_prompt": "be helpful",
            "providers_config": {"openrouter": {"model": "test/model"}},
        }),
        raising=False,
    )


def _request(**overrides):
    payload = {"session_id": 1, "message": "what is the capital of France?", "provider_id": "openrouter", "model": "test/model"}
    payload.update(overrides)
    return ConversationRequest.from_payload(payload, session_id=1)


def _classifier(result):
    class C:
        def classify(self, request):
            if isinstance(result, Exception):
                raise result
            return result

    return C()


def test_dispatch_direct():
    decision = DeterministicDispatcher().dispatch(_request())
    assert decision.route is Route.DIRECT_RESPONSE
    assert decision.reason_codes == ("ordinary_question",)
    assert decision.provider_id == "openrouter" and decision.model == "test/model"


def test_dispatch_provider_preserved():
    request = _request(provider_id="groq", model="other/model")
    decision = DeterministicDispatcher().dispatch(request)
    assert decision.provider_id == "groq" and decision.model == "other/model"


def test_dispatch_unknown_workflow_needs_input():
    decision = DeterministicDispatcher().dispatch(_request(message=WORKFLOW_PREFIX + "nonexistent now"))
    assert decision.route is Route.NEEDS_USER_INPUT


def test_dispatch_registered_workflow():
    dispatcher = DeterministicDispatcher(workflows={"cleanup": "clean"})
    decision = dispatcher.dispatch(_request(message=WORKFLOW_PREFIX + "cleanup arg"))
    assert decision.route is Route.DETERMINISTIC_WORKFLOW


def test_dispatch_workflow_does_not_require_a_model():
    dispatcher = DeterministicDispatcher(workflows={"provider_operational_report": "provider_operational_report"})
    decision = dispatcher.dispatch(_request(
        message=WORKFLOW_PREFIX + "provider_operational_report",
        provider_id=None,
        model=None,
    ))
    assert decision.route is Route.DETERMINISTIC_WORKFLOW
    assert decision.reason_codes == ("registered_workflow", "provider_operational_report")


def test_dispatch_explicit_delegation():
    decision = DeterministicDispatcher().dispatch(_request(message=DELEGATION_PREFIX + "do the research task"))
    assert decision.route is Route.AGENT_DELEGATION


def test_dispatch_delegation_unavailable_blocks():
    dispatcher = DeterministicDispatcher(orchestration_available=False)
    decision = dispatcher.dispatch(_request(force_delegation=True))
    assert decision.route is Route.BLOCKED
    assert "delegation_unavailable" in decision.reason_codes


def test_missing_model_blocks():
    decision = DeterministicDispatcher().dispatch(_request(provider_id="openrouter", model=""))
    assert decision.route is Route.BLOCKED
    assert "no_model_selected" in decision.reason_codes


def test_classifier_valid_advisory_proposal_honored():
    dispatcher = DeterministicDispatcher(classifier=_classifier((Route.NEEDS_USER_INPUT, "ambiguous_destructive_intent")))
    decision = dispatcher.dispatch(_request())
    assert decision.route is Route.NEEDS_USER_INPUT
    assert decision.provider_id is None


def test_classifier_cannot_delegate_or_block():
    for proposal in ((Route.AGENT_DELEGATION, "model_wants_delegation"), (Route.BLOCKED, "model_blocked")):
        dispatcher = DeterministicDispatcher(classifier=_classifier(proposal))
        decision = dispatcher.dispatch(_request())
        assert decision.route is Route.DIRECT_RESPONSE


def test_classifier_invalid_schema_falls_back():
    dispatcher = DeterministicDispatcher(classifier=_classifier(("explode_system", "bad_code")))
    decision = dispatcher.dispatch(_request())
    assert decision.route is Route.DIRECT_RESPONSE


def test_classifier_failure_falls_back():
    dispatcher = DeterministicDispatcher(classifier=_classifier(RuntimeError("model down")))
    decision = dispatcher.dispatch(_request())
    assert decision.route is Route.DIRECT_RESPONSE


def test_workflows_registry_defaults_empty():
    assert DETERMINISTIC_WORKFLOWS == {}
