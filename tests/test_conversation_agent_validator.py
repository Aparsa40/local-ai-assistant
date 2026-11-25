from core.conversation_agent.contracts import ExecutionMode, ExecutionStatus, ResponseCandidate, ValidationState
from core.conversation_agent.validator import ResponseValidator
import pytest


def _candidate(**overrides):
    data = {
        "content": "an answer",
        "status": ExecutionStatus.COMPLETED,
        "mode": ExecutionMode.ONLINE,
    }
    data.update(overrides)
    return ResponseCandidate(**data)


def test_valid_candidate():
    report = ResponseValidator().validate(_candidate())
    assert report.state is ValidationState.VALID
    assert report.ok


def test_empty_candidate_rejected():
    report = ResponseValidator().validate(_candidate(content="   "))
    assert report.state is ValidationState.REJECTED


def test_unknown_reference_is_partial_not_proof():
    report = ResponseValidator().validate(_candidate(source_refs=("message:999",)), context_refs=frozenset({"message:1"}))
    assert report.state is ValidationState.PARTIAL
    assert report.issues[0].code == "unknown_reference"


def test_known_reference_passes():
    report = ResponseValidator().validate(_candidate(source_refs=("message:1",)), context_refs=frozenset({"message:1"}))
    assert report.state is ValidationState.VALID


def test_failed_status_rejected_never_fabricates_success():
    report = ResponseValidator().validate(_candidate(status=ExecutionStatus.FAILED, content="", error_code="inference_failed"))
    assert report.state is ValidationState.REJECTED


def test_claimed_success_with_incomplete_tasks_rejected():
    candidate = _candidate(node_outcomes=({"node_id": "n1", "status": "failed"},))
    report = ResponseValidator().validate(candidate)
    assert report.state is ValidationState.REJECTED
    assert "incomplete_task_coverage" in {issue.code for issue in report.issues}


def test_running_tasks_not_terminal():
    report = ResponseValidator().validate(_candidate(node_outcomes=({"node_id": "n1", "status": "running"},)))
    assert {i.code for i in report.issues} >= {"tasks_not_terminal"}


def test_completed_node_without_evidence_flagged():
    candidate = _candidate(node_outcomes=({"node_id": "n1", "status": "completed", "handoff_status": "partial"},))
    report = ResponseValidator().validate(candidate)
    assert {i.code for i in report.issues} >= {"missing_evidence"}


def test_fallback_requires_disclosure():
    with pytest.raises(Exception):
        _candidate(fallback_applied=True)
