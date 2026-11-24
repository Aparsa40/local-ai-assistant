"""Deterministic completion evaluation against declared completion criteria.

The evaluator is trusted application code. It inspects only the bounded,
structured outcome dictionary and reports both whether the declared criteria
were met and a truthful completion status; it never silently marks partial
work as fully complete.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.agents.contracts import AgentDefinition


@dataclass(frozen=True, slots=True)
class EvaluationVerdict:
    """Truthful completion verdict for one run outcome."""

    status: str
    criteria_met: bool
    reason: str


class CompletionEvaluator:
    """Evaluates outcome dictionaries against the declared CompletionCriteria."""

    def evaluate(self, definition: AgentDefinition, outcome) -> EvaluationVerdict:
        if not isinstance(outcome, dict):
            return EvaluationVerdict("incomplete", False, "The outcome is not a structured object.")
        kind = definition.completion.kind
        minimum = definition.completion.min_results
        if kind == "sources_collected":
            results = outcome.get("results")
            count = len(results) if isinstance(results, (list, tuple)) else 0
            reason = (
                str(count) + " source(s) collected; the completion minimum is " + str(minimum) + "."
            )
        elif kind == "deterministic_steps_done":
            steps = outcome.get("steps_done")
            count = len(steps) if isinstance(steps, (list, tuple)) else (
                steps if isinstance(steps, int) and not isinstance(steps, bool) else 0
            )
            reason = (
                str(count) + " step(s) reported done; the completion minimum is " + str(minimum) + "."
            )
        elif kind == "structured_result_present":
            result = outcome.get("result")
            present = result is not None and result != "" and result != {} and result != []
            count = 1 if present else 0
            reason = (
                "A structured result was reported."
                if present else "No structured result was reported."
            )
        else:
            return EvaluationVerdict("incomplete", False, "The completion kind is not supported.")
        met = count >= minimum
        return EvaluationVerdict(
            "complete" if met else "incomplete",
            met,
            reason,
        )
