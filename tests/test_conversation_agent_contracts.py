import pytest

from core.conversation_agent.contracts import (
    EVENT_PROTOCOL_VERSION,
    EVENT_TYPES,
    ConversationEvent,
    ConversationRequest,
    ContractValidationError,
    DataScopeRef,
    DispatchDecision,
    ExecutionBudget,
    Route,
    ValidationIssue,
    ValidationReport,
    ValidationState,
    new_request_id,
    redact_payload,
)


def _payload(**overrides):
    payload = {
        "session_id": 1,
        "message": "hello there",
        "request_id": "req_" + "a" * 24,
        "provider_id": "openrouter",
        "model": "m1",
    }
    payload.update(overrides)
    return payload


def test_from_payload_round_trip_valid():
    request = ConversationRequest.from_payload(_payload(), session_id=1)
    assert request.session_id == 1
    assert request.request_id == "req_" + "a" * 24
    assert request.provider_id == "openrouter"
    assert request.budget.max_output_chars == 40000


def test_missing_request_id_is_minted():
    request = ConversationRequest.from_payload({"session_id": 3, "message": "hi"}, session_id=3)
    assert request.request_id.startswith("req_")
    assert len(request.request_id) == 28


@pytest.mark.parametrize("payload", [
    _payload(message="   "),
    _payload(message="x" * 12001),
    _payload(request_id="short"),
    _payload(schema_version=99),
    _payload(provider_id="OpenRouter"),
    _payload(authorize_private_context_egress="false"),
    _payload(force_delegation="false"),
    _payload(history_limit=0),
    _payload(memory_scopes=[{"domain": "other", "scope_type": "user", "scope_id": "1", "owner_id": "local-user"}]),
])
def test_invalid_payloads_rejected(payload):
    with pytest.raises(ContractValidationError):
        ConversationRequest.from_payload(payload, session_id=1)


def test_scope_lists_bounded():
    with pytest.raises(ContractValidationError):
        ConversationRequest.from_payload(
            _payload(knowledge_scopes=[{"domain": "knowledge", "scope_type": "user", "scope_id": str(i), "owner_id": "local-user"} for i in range(11)]),
            session_id=1,
        )


def test_metadata_type_validation():
    request = ConversationRequest.from_payload(_payload(client_metadata={"owner_id": "local-user"}), session_id=1)
    assert request.client_metadata["owner_id"] == "local-user"
    with pytest.raises(ContractValidationError):
        ConversationRequest.from_payload(_payload(client_metadata={"nested": {"bad": True}}), session_id=1)


def test_dispatch_decision_contract():
    decision = DispatchDecision(route=Route.DIRECT_RESPONSE, reason_codes=("ordinary_question",))
    assert decision.to_dict()["route"] == "direct_response"
    with pytest.raises(ContractValidationError):
        DispatchDecision(route="direct_response", reason_codes=("x",))
    with pytest.raises(ContractValidationError):
        DispatchDecision(route=Route.BLOCKED, reason_codes=())


def test_budget_bounds():
    ExecutionBudget(wall_clock_seconds=30).validate()
    with pytest.raises(ContractValidationError):
        ExecutionBudget(wall_clock_seconds=4000).validate()


def test_validation_report_contract():
    report = ValidationReport(state=ValidationState.PARTIAL, issues=(ValidationIssue("unknown_reference", "detail"),))
    assert report.ok is False
    with pytest.raises(ContractValidationError):
        ValidationReport(state=ValidationState.PARTIAL)
    with pytest.raises(ContractValidationError):
        ValidationReport(state=ValidationState.REJECTED)


def test_event_protocol():
    event = ConversationEvent("evt_1", "req_" + "a" * 24, 1, "status", {"detail": "x"})
    rendered = event.to_sse()
    assert rendered.startswith("data: ")
    assert "evt_1" in rendered
    assert EVENT_PROTOCOL_VERSION == 1
    with pytest.raises(ContractValidationError):
        ConversationEvent("evt_1", "req_" + "a" * 24, 1, "hidden_reasoning", {})
    assert "hidden_reasoning" not in EVENT_TYPES


def test_redact_payload_drops_unknown_keys():
    redacted = redact_payload({
        "status": "completed",
        "provider_id": "openrouter",
        "system_prompt": "SECRET-PROMPT",
        "api_key": "SECRET",
        "reason_codes": ["ordinary_question"],
        "deep": {"status": "ok", "secret": "drop-me"},
    })
    assert redacted == {"status": "completed", "provider_id": "openrouter", "reason_codes": ["ordinary_question"], "deep": {"status": "ok"}}


def test_data_scope_ref_domain():
    DataScopeRef("knowledge", "user", "1", "local-user").validate()
    with pytest.raises(ContractValidationError):
        DataScopeRef("filesystem", "user", "1", "local-user").validate()
