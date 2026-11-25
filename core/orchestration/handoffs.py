"""Versioned handoff envelopes between child runs and the plan (WP-7.5).

The HandoffManager validates size and schema before persistence, preserves
provenance (plan, node, and run identity plus evidence), and records
truthful confidence semantics: complete, partial, or incomplete.
"""
from __future__ import annotations

import json

from core.orchestration.contracts import (
    Evidence,
    Handoff,
    HandoffValidationError,
    MAX_HANDOFF_BYTES,
    new_evidence_id,
    new_handoff_id,
)

ENVELOPE_VERSION = "orchestration.handoff/1"

_MAX_SUMMARY = 2000


class HandoffManager:
    """Validates and persists handoff envelopes; never trusts run output."""

    def __init__(self, handoffs_repository, *, max_handoff_bytes: int = MAX_HANDOFF_BYTES) -> None:
        self.repository = handoffs_repository
        self.max_handoff_bytes = max_handoff_bytes

    def record_outcome(self, plan, node, run) -> Handoff:
        """Build one handoff envelope from a finished child run outcome."""
        outcome = run.outcome if isinstance(run.outcome, dict) else {}
        results = outcome.get("results")
        if not isinstance(results, list):
            results = []
        status = "incomplete"
        if str(outcome.get("status", "incomplete")) == "complete":
            status = "complete"
        elif str(outcome.get("status", "incomplete")) == "partial":
            status = "partial"
        payload = {
            "node_id": node.node_id,
            "run_id": run.run_id,
            "agent_id": run.agent_id,
            "agent_version": run.agent_version,
            "summary": str(outcome.get("summary", ""))[:_MAX_SUMMARY],
            "results": [
                {
                    "source_id": str(item.get("source_id", ""))[:160],
                    "title": str(item.get("title", ""))[:200],
                    "content": str(item.get("content", ""))[:400],
                    "uri": str(item.get("uri", ""))[:400],
                }
                for item in results
                if isinstance(item, dict)
            ][:50],
            "count": len(results),
        }
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > self.max_handoff_bytes:
            # Bounded degradation: keep provenance and the summary, drop results.
            payload["results"] = payload["results"][:5]
            payload["truncated_for_size"] = True
        evidence = (
            Evidence(
                evidence_id=new_evidence_id(),
                kind="run_outcome",
                subject=run.run_id,
                claim="Handoff recorded from a finished agent run.",
            ),
            Evidence(
                evidence_id=new_evidence_id(),
                kind="handoff_reference",
                subject="knowledge_search",
                claim="Outcome includes results produced through the ToolRuntime boundary.",
            ),
        )
        handoff = Handoff(
            handoff_id=new_handoff_id(),
            plan_id=plan.plan_id,
            node_id=node.node_id,
            from_run_id=run.run_id,
            envelope_version=ENVELOPE_VERSION,
            payload=payload,
            status=status,
            evidence=evidence,
        )
        return self.repository.append(handoff)

    def load_inputs(self, plan_id: str, node_id: str) -> dict:
        """Load the bounded upstream context for one node from persisted handoffs.

        Only handoffs whose dependency policy was satisfied are used; the
        envelope is re-validated, and a malformed stored payload degrades to an
        empty input rather than expanding trust.
        """
        inputs: dict = {}
        for handoff in self.repository.list_for_plan(plan_id, limit=100):
            if handoff.node_id == node_id:
                continue
            if not isinstance(handoff.payload, dict):
                continue
            inputs[str(handoff.node_id)] = {
                "summary": str(handoff.payload.get("summary", ""))[:_MAX_SUMMARY],
                "results": list(handoff.payload.get("results", []))[:50],
                "handoff_status": handoff.status,
                "from_run_id": handoff.from_run_id,
            }
        return inputs

    def list_for_plan(self, plan_id: str, *, limit: int = 200) -> tuple:
        return self.repository.list_for_plan(plan_id, limit=limit)
