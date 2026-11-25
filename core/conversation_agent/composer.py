"""Compose truthful final messages from validated candidates (WP-8.5)."""
from __future__ import annotations

from .contracts import ResponseCandidate, ValidationReport, ValidationState


_TERM_LANGUAGE = {
    "failed": "The execution failed and no answer was produced.",
    "cancelled": "The request was cancelled before completion.",
    "blocked": "The request was blocked by policy before execution.",
    "unavailable": "No eligible execution path was available; nothing was fabricated.",
    "needs_input": "Your input is required before this request can proceed.",
}


class ResponseComposer:
    def compose(
        self,
        candidate: ResponseCandidate,
        report: ValidationReport,
        *,
        reason_text: str | None = None,
    ) -> tuple[str, str]:
        """Return (final_content, final_status) preserving limitations truthfully."""
        if report.state is ValidationState.REJECTED:
            base = _TERM_LANGUAGE.get(candidate.status.value, "The request did not complete successfully.")
            if reason_text:
                base = reason_text
            notes = list(candidate.limitations)
            if notes:
                base += "\n\nLimitations:\n" + "\n".join("- " + note for note in notes)
            return base, candidate.status.value

        content = candidate.content
        notes = list(candidate.limitations)
        if candidate.fallback_applied and candidate.fallback_reason:
            notes.append("Fallback executed: " + candidate.fallback_reason)
        if notes:
            content = content.rstrip() + "\n\nLimitations:\n" + "\n".join("- " + note for note in notes)
        return content, candidate.status.value
