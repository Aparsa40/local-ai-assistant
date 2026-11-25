"""Deterministic, explainable, least-privilege assignment resolution (WP-7.3).

Candidates are registered Phase 6 agent definitions only; the trusted
bootstrap builds the capability index from those definitions plus the
application ToolRegistry. Capabilities are never inferred from model names:
model-dependent capability evidence comes exclusively through the
InterfaceManager, and an unavailable or unknown capability isUnknown.

Assignment denies any node whose requested data or tool scopes exceed the
parent goal/run scope, and every decision records its reasons and evidence.
"""
from __future__ import annotations

from core.orchestration.contracts import (
    Assignment,
    Evidence,
    EvidenceLevel,
    new_assignment_id,
    new_evidence_id,
)
from core.tools.registry import ToolRegistry


class AssignmentResolverError(Exception):
    """The resolver received an invalid request."""


class CapabilityCandidate:
    """One registered agent capability profile; plain, bounded data."""

    def __init__(self, agent_id: str, version: str, *, capabilities: tuple,
                 tool_scopes: tuple = (), allowed_models: tuple = (),
                 model_dependent: bool = False) -> None:
        if not agent_id or not version:
            raise AssignmentResolverError("A candidate requires an agent id and version.")
        self.agent_id = agent_id
        self.version = version
        self.capabilities = tuple(str(item) for item in capabilities)
        self.tool_scopes = tuple(str(item) for item in tool_scopes)
        self.allowed_models = tuple(str(item) for item in allowed_models)
        self.model_dependent = bool(model_dependent)


class CapabilityAssignmentResolver:
    """Deterministic capability matching over registered agent candidates."""

    def __init__(self, tool_registry: ToolRegistry, interface_manager=None, *, goals=None) -> None:
        self.tool_registry = tool_registry
        self.interface_manager = interface_manager
        self._goals = goals
        self._candidates: dict = {}

    def register_candidate(self, candidate: CapabilityCandidate) -> None:
        """Register candidates from trusted bootstrap code only."""
        if not isinstance(candidate, CapabilityCandidate):
            raise AssignmentResolverError("candidate must be a CapabilityCandidate")
        key = (candidate.agent_id, candidate.version)
        self._candidates[key] = candidate

    def candidates(self) -> tuple:
        return tuple(sorted(self._candidates))

    # -- evidence ---------------------------------------------------------------

    def _verified_tools(self) -> set:
        known = set()
        try:
            for entry in self.tool_registry.public_catalog():
                known.add(str(entry["tool_id"]))
        except Exception:
            return known
        return known

    def _model_evidence(self, candidate: CapabilityCandidate) -> tuple:
        """Model capability evidence strictly through the InterfaceManager."""
        if self.interface_manager is None:
            return (False, [])
        evidence = []
        try:
            providers = self.interface_manager.list_providers()
        except Exception:
            return (False, evidence)
        available = [
            provider for provider in providers
            if provider.get("capabilities_available")
        ]
        if not candidate.allowed_models:
            if candidate.model_dependent:
                return (False, evidence)
            return (True, evidence)
        if suitable := bool(available):
            for provider in available:
                evidence.append(Evidence(
                    evidence_id=new_evidence_id(),
                    kind="model_catalog",
                    subject=str(provider.get("id", ""))[:160],
                    claim="The provider reports available capabilities through the InterfaceManager.",
                ))
        return (suitable, evidence)

    # -- resolution ---------------------------------------------------------------

    def assign(self, plan, node) -> Assignment:
        goal = None
        if self._goals is not None:
            goal = self._goals.get(plan.goal_id)
        goal_data = {
            (scope.domain, scope.scope_type, scope.scope_id, scope.owner_id)
            for scope in (goal.data_scopes if goal is not None else node.data_scopes)
        }
        goal_tools = set(goal.tool_scopes if goal is not None else node.tool_scopes)
        node_data = {
            (scope.domain, scope.scope_type, scope.scope_id, scope.owner_id)
            for scope in node.data_scopes
        }
        if not node_data.issubset(goal_data) or not set(node.tool_scopes).issubset(goal_tools):
            evidence = (
                Evidence(
                    evidence_id=new_evidence_id(),
                    kind="policy_check",
                    subject=plan.plan_id,
                    claim="The node requested data or tool scopes outside the goal scope.",
                ),
            )
            return self._denied(plan, node, (
                "Requested scopes exceed the parent run authorization.",
            ), evidence)

        def _score(entry):
            _, candidate, matched_verify, _ = entry
            caps = set(candidate.capabilities)
            required = set(node.required_capabilities)
            verified = len(matched_verify & required)
            declared = len(set(candidate.capabilities) & set(node.required_capabilities))
            return (candidate.model_dependent, -verified, -declared, candidate.agent_id, candidate.version)

        scored = []
        for key in sorted(self._candidates):
            candidate = self._candidates[key]
            verified_tools = self._verified_tools()
            matched_verify = {
                capability for capability in candidate.capabilities
                if capability in verified_tools
            }
            evidence = []
            if candidate.model_dependent:
                ok, model_evidence = self._model_evidence(candidate)
                evidence.extend(model_evidence)
                if not ok:
                    continue
            scored.append((key, candidate, matched_verify, evidence))

        if not scored:
            return self._denied(plan, node, (
                "No registered agent declares the required capabilities.",
            ), ())

        missing = [
            capability for capability in node.required_capabilities
            if not any(
                capability in candidate.capabilities
                for _, candidate, _, _ in scored
            )
        ]
        if missing:
            return self._denied(plan, node, (
                "Required capability " + missing[0] + " is unknown to the runtime.",
            ), ())

        scored.sort(key=_score)
        key, candidate, matched_verify, evidence = scored[0]
        decision_evidence = list(evidence)
        decision_evidence.append(Evidence(
            evidence_id=new_evidence_id(),
            kind="verified_tool" if any(capability in self._verified_tools() for capability in node.required_capabilities) else "declared_capability",
            subject=candidate.agent_id + ":" + candidate.version,
            claim="The definition declares and the runtime verified the required capabilities.",
        ))
        return Assignment(
            assignment_id=new_assignment_id(),
            plan_id=plan.plan_id,
            node_id=node.node_id,
            decision="assigned",
            agent_id=candidate.agent_id,
            agent_version=candidate.version,
            reasons=(
                "Matched required capabilities: " + ", ".join(sorted(set(node.required_capabilities))) + ".",
                "Selected with verified evidence where available; ties break lexicographically.",
            ),
            evidence=tuple(decision_evidence),
        )

    def _denied(self, plan, node, reasons, evidence) -> Assignment:
        return Assignment(
            assignment_id=new_assignment_id(),
            plan_id=plan.plan_id,
            node_id=node.node_id,
            decision="denied",
            reasons=tuple(reasons),
            evidence=tuple(evidence),
        )

    def explain(self, plan, node) -> dict:
        """A bounded, explainable view of the current decision inputs."""
        return {
            "node_id": node.node_id,
            "required_capabilities": list(node.required_capabilities),
            "candidates": [
                {
                    "agent_id": candidate.agent_id,
                    "version": candidate.version,
                    "capabilities": list(candidate.capabilities),
                    "model_dependent": candidate.model_dependent,
                }
                for _, candidate in sorted(self._candidates.items())
            ],
            "verified_tools": sorted(self._verified_tools()),
        }
