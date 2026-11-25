from core.conversation_agent.composer import ResponseComposer
from core.conversation_agent.contracts import (
    ExecutionMode,
    ExecutionStatus,
    ResponseCandidate,
    ValidationIssue,
    ValidationReport,
    ValidationState,
)


def _report(state, issues=()):
    return ValidationReport(state=state, issues=tuple(issues))


def test_valid_compose_preserves_limitations_and_fallback():
    candidate = ResponseCandidate(
        content="the answer", status=ExecutionStatus.COMPLETED, mode=ExecutionMode.ONLINE,
        fallback_applied=True, fallback_reason="local not ready", limitations=("partial context",),
    )
    content, status = ResponseComposer().compose(candidate, _report(ValidationState.VALID))
    assert content.startswith("the answer")
    assert "local not ready" in content
    assert "partial context" in content
    assert status == "completed"


def test_rejected_compose_is_truthful():
    candidate = ResponseCandidate(
        content="", status=ExecutionStatus.FAILED, mode=ExecutionMode.ONLINE, error_code="inference_failed",
    )
    content, status = ResponseComposer().compose(
        candidate,
        _report(ValidationState.REJECTED, (ValidationIssue("non_success_status", "x"),)),
    )
    assert "failed" in content
    assert status == "failed"
