"""Response validation (WP-8.5). Model output is untrusted input."""
from __future__ import annotations

from .contracts import (
    ExecutionStatus,
    ResponseCandidate,
    ValidationIssue,
    ValidationReport,
    ValidationState,
)


class ResponseValidator:
    """Validate a candidate against schema, references, coverage and policy."""

    def __init__(self, *, max_content_chars: int = 40000) -> None:
        self._max_content_chars = max_content_chars

    def validate(
        self,
        candidate: ResponseCandidate,
        *,
        context_refs: frozenset[str] = frozenset(),
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        schema_ok = True
        references_ok = True
        coverage_ok = True
        policy_ok = True

        content = candidate.content or ""
        if not content.strip():
            schema_ok = False
            issues.append(ValidationIssue("empty_response", "The candidate contained no user-facing content."))
        elif len(content) > self._max_content_chars:
            schema_ok = False
            issues.append(ValidationIssue("output_exceeds_budget", "The candidate exceeded the output budget and was truncated."))

        # Reference existence: a source reference that was never retrieved is a
        # fabricated citation. Existence is not proof of factual correctness.
        for ref in candidate.source_refs:
            if context_refs and ref not in context_refs:
                references_ok = False
                issues.append(ValidationIssue("unknown_reference", "A cited source reference was not part of the retrieved context."))
                break

        # Delegated candidates must cover their required tasks truthfully.
        if candidate.node_outcomes:
            statuses = [str(node.get("status", "unknown")) for node in candidate.node_outcomes]
            if any(status in {"running", "pending"} for status in statuses):
                coverage_ok = False
                issues.append(ValidationIssue("tasks_not_terminal", "Delegated tasks did not reach a terminal state."))
            if candidate.status is ExecutionStatus.COMPLETED and any(status != "completed" for status in statuses):
                coverage_ok = False
                issues.append(ValidationIssue("incomplete_task_coverage", "Success was claimed while required tasks remained incomplete."))
            if candidate.status is ExecutionStatus.COMPLETED and not any(
                str(node.get("handoff_status", "")) == "complete" for node in candidate.node_outcomes if "handoff_status" in node
            ) and any("handoff_status" in node for node in candidate.node_outcomes):
                coverage_ok = False
                issues.append(ValidationIssue("missing_evidence", "A completed task recorded no handoff evidence."))

        # Policy: failure states must never validate as a usable answer.
        if candidate.status in {
            ExecutionStatus.FAILED, ExecutionStatus.BLOCKED, ExecutionStatus.CANCELLED,
            ExecutionStatus.UNAVAILABLE, ExecutionStatus.NEEDS_INPUT,
        }:
            policy_ok = False
            issues.append(ValidationIssue("non_success_status", "Execution did not complete; the candidate cannot be presented as an answer."))

        if not issues:
            state = ValidationState.VALID
        elif schema_ok and references_ok and coverage_ok and policy_ok and candidate.status is ExecutionStatus.COMPLETED:
            state = ValidationState.PARTIAL
        else:
            state = ValidationState.REJECTED
        return ValidationReport(
            state=state,
            issues=tuple(issues),
            schema_ok=schema_ok,
            references_ok=references_ok,
            coverage_ok=coverage_ok,
            policy_ok=policy_ok,
        )
