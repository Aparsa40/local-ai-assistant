"""The one initial Phase 6 agent: a deterministic knowledge analysis task.

This agent performs a low-risk, read-only workflow: it searches one explicitly
bound knowledge scope through ToolRuntime and reports the collected sources.
It uses no model calls; budgets intentionally leave the model token budget at
zero so that no implicit provider transmission can occur.
"""
from __future__ import annotations

from core.agents.contracts import AgentBudgets, AgentDefinition, CompletionCriteria

AGENT_ID = "knowledge-analyzer"
AGENT_VERSION = "1.0.0"
KNOWLEDGE_SEARCH_TOOL_ID = "knowledge_search"


class KnowledgeAnalysisAgent:
    """Deterministic behavior: search the bound scope, then report sources."""

    max_results: int = 5

    @staticmethod
    def definition() -> AgentDefinition:
        return AgentDefinition(
            agent_id=AGENT_ID,
            version=AGENT_VERSION,
            goal=(
                "Analyze the task query against one explicitly bound knowledge "
                "scope and report the collected sources truthfully."
            ),
            description=(
                "A bounded, deterministic knowledge-analysis agent. It issues one "
                "read-only knowledge search through ToolRuntime and reports the "
                "sources it found. It never writes, deletes, publishes, or "
                "transmits data to external providers."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            output_schema={
                "type": "object",
                "properties": {},
            },
            completion=CompletionCriteria(
                kind="sources_collected",
                description="At least one knowledge source was collected and reported.",
                min_results=1,
            ),
            budgets=AgentBudgets(
                max_iterations=6,
                deadline_seconds=120,
                max_tool_calls=4,
                max_model_tokens=0,
            ),
            allowed_tools=(KNOWLEDGE_SEARCH_TOOL_ID,),
            allowed_models=(),
            data_scopes=("knowledge",),
            approval_policy="explicit",
        )

    def decide(self, ctx, state) -> dict:
        observations = state.get("observations") or []
        if not observations:
            return self._first_action(ctx)
        last = observations[-1]
        if last.get("kind") == "tool":
            if last.get("ok") is True:
                return {
                    "kind": "finish",
                    "status": "complete",
                    "outcome": {
                        "summary": "Knowledge scope analysis completed.",
                        "results": last.get("output", {}).get("results", []),
                        "count": last.get("count", 0),
                        "status": "completed",
                    },
                }
            return {
                "kind": "finish",
                "status": "incomplete",
                "outcome": {
                    "summary": "The knowledge search could not be completed.",
                    "reason_code": last.get("error_category", "unknown"),
                    "results": [],
                    "count": 0,
                    "status": "incomplete",
                },
            }
        if last.get("kind") == "model":
            return {
                "kind": "finish",
                "status": "incomplete",
                "outcome": {
                    "summary": "Model-assisted analysis is not part of this deterministic agent.",
                    "reason_code": last.get("reason_code", "model_unavailable"),
                    "results": [],
                    "count": 0,
                    "status": "incomplete",
                },
            }
        return {
            "kind": "finish",
            "status": "incomplete",
            "outcome": {
                "summary": "The agent could not continue its bounded workflow.",
                "reason_code": "unexpected_observation",
                "results": [],
                "count": 0,
                "status": "incomplete",
            },
        }

    def _first_action(self, ctx) -> dict:
        scopes = ctx.binding.knowledge_scopes
        if not scopes:
            return {
                "kind": "finish",
                "status": "incomplete",
                "outcome": {
                    "summary": "No knowledge scope was bound to this run.",
                    "reason_code": "missing_scope_binding",
                    "results": [],
                    "count": 0,
                    "status": "incomplete",
                },
            }
        scope = scopes[0]
        return {
            "kind": "tool",
            "tool_id": KNOWLEDGE_SEARCH_TOOL_ID,
            "input": {
                "run_id": ctx.run_id,
                "scope_type": scope.scope_type,
                "scope_id": scope.scope_id,
                "owner_id": scope.owner_id,
                "query": (ctx.query or "")[:2000],
                "limit": self.max_results,
            },
            "purpose": "Search the bound knowledge scope for the task query.",
        }
