"""Bounded planning service (WP-7.4): deterministic templates and vetted proposals.

The planning service builds plans two ways:
- deterministic templates derived from the goal's explicit scopes; and
- structured LLM proposals that are parsed, schema-checked, graph-validated,
  and policy-checked before acceptance.

Policy invariants enforced here:
- A model proposal is untrusted input: it must match the bounded proposal
  schema, must not carry nested plan fields (recursive decomposition is
  rejected), and must not exceed the goal's budgets or scopes.
- The Supervisor never issues grants or approvals: the planning service has no
  permission or approval dependency at all.
- Plan revisions are bounded and monotonic.

All model calls requested through this service use the InterfaceManager
exclusively; in Phase 7 the supervisor conversation behavior is deterministic,
so the LLM proposal path is opt-in per orchestration request.
"""
from __future__ import annotations

import json
import re
from uuid import uuid4

from core.agents.contracts import CompletionCriteria, DataScope
from core.orchestration.contracts import (
    MAX_PLAN_NODES,
    Dependency,
    Goal,
    NodeStatus,
    Plan,
    PlanStatus,
    PlanValidationError,
    TaskNode,
    new_dependency_id,
    new_plan_id,
)
from core.orchestration.graph import validate_plan

PLANNING_SCHEMA_VERSION = "orchestration.proposal/1"
DEFAULT_PLANNING_CAPABILITY = "knowledge_search"
_PROPOSAL_MAX_BYTES = 128 * 1024

_HEX32 = re.compile(r"[0-9a-f]{32}")

_NESTED_PLAN_KEYS = {"plan", "plans", "subplan", "subplans", "proposal", "proposals"}


class ProposalRejected(PlanValidationError):
    """A model-produced plan proposal failed validation or policy."""


class ActorRegistrationError(PlanValidationError):
    """A supervisor definition change was attempted outside trusted code."""


def build_template_plan(goal: Goal, *, parent_run_id: str, parent_task_id: str, plan_id=None) -> Plan:
    """Deterministic template: one bounded analysis node per goal data scope.

    Templates change only with trusted application code; they never reflect
    model output. A goal without data scopes is rejected here rather than
    producing a plan whose nodes could only be denied later at assignment.
    """
    if not goal.data_scopes:
        raise PlanValidationError(
            "A deterministic plan requires at least one explicit goal data scope."
        )
    if not goal.tool_scopes or DEFAULT_PLANNING_CAPABILITY not in goal.tool_scopes:
        raise PlanValidationError(
            "A deterministic plan requires the " + DEFAULT_PLANNING_CAPABILITY + " tool scope."
        )
    if len(goal.data_scopes) > MAX_PLAN_NODES:
        raise PlanValidationError("The goal exceeds the maximum plan node count.")
    resolved_plan_id = plan_id or new_plan_id()
    nodes = []
    for ordinal, scope in enumerate(goal.data_scopes):
        nodes.append(TaskNode(
            node_id=uuid4().hex,
            plan_id=resolved_plan_id,
            ordinal=ordinal,
            title=("Analyze scope " + scope.scope_id)[:200],
            required_capabilities=(DEFAULT_PLANNING_CAPABILITY,),
            acceptance=CompletionCriteria(
                kind="structured_result_present",
                description=goal.success_criteria[:500],
            ),
            payload={
                "query": goal.description[:2000],
                "scope_id": scope.scope_id,
                "domain": scope.domain,
            },
            data_scopes=(scope,),
            tool_scopes=(DEFAULT_PLANNING_CAPABILITY,),
            status=NodeStatus.PENDING,
            max_retries=goal.budgets.max_retries_per_task,
        ))
    return Plan(
        plan_id=resolved_plan_id,
        goal_id=goal.goal_id,
        parent_run_id=parent_run_id,
        parent_task_id=parent_task_id,
        owner_id=goal.owner_id,
        revision=0,
        status=PlanStatus.DRAFT,
        nodes=tuple(nodes),
        dependencies=(),
        budgets=goal.budgets,
        acceptance=CompletionCriteria(
            kind="structured_result_present",
            description=goal.success_criteria[:500],
        ),
        created_at=goal.created_at,
    )


class PlanningService:
    """Deterministic template planning plus bounded, schema-validated proposals."""

    max_plan_revisions: int = 2

    def __init__(self, *, events=None) -> None:
        self.events = events

    # -- deterministic path -----------------------------------------------------

    def build_plan(
        self, goal: Goal, *, parent_run_id: str, parent_task_id: str, plan_id=None,
    ) -> Plan:
        plan = build_template_plan(
            goal, parent_run_id=parent_run_id, parent_task_id=parent_task_id, plan_id=plan_id,
        )
        validate_plan(plan, goal=goal)
        return plan

    # -- bounded LLM proposal path ---------------------------------------------

    def build_plan_from_proposal(
        self, goal: Goal, proposal_text, *, parent_run_id: str, parent_task_id: str, revision: int = 1,
    ) -> Plan:
        """Parse and validate an untrusted model proposal into a draft plan."""
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ProposalRejected("revision must be a positive integer")
        if revision > self.max_plan_revisions:
            raise ProposalRejected(
                "The plan revision budget is exhausted; further revisions are rejected."
            )
        proposal = self._parse_proposal_text(proposal_text)
        if proposal.get("schema") != PLANNING_SCHEMA_VERSION:
            raise ProposalRejected("The proposal schema version is unsupported.")
        if proposal.get("goal_id") != goal.goal_id:
            raise ProposalRejected("The proposal must target the current goal.")
        nodes_payload = proposal.get("nodes")
        dependency_payload = proposal.get("dependencies")
        if not isinstance(nodes_payload, list) or not nodes_payload:
            raise ProposalRejected("The proposal must declare at least one node.")
        if len(nodes_payload) > goal.budgets.max_nodes or len(nodes_payload) > MAX_PLAN_NODES:
            raise ProposalRejected("The proposal exceeds its node budget.")
        if not isinstance(dependency_payload, list):
            raise ProposalRejected("The proposal dependencies must be a list.")
        for schema in nodes_payload:
            if not self._bounded_node(schema):
                raise ProposalRejected("The proposal contains an unsupported node schema.")
            _reject_nested_plan_fields(schema["payload"])
            if any(
                isinstance(value, dict) and _contains_plan_key(value)
                for value in schema["payload"].values()
            ):
                raise ProposalRejected("Recursive decomposition within a node payload is rejected.")
        for item in dependency_payload:
            self._validate_dependency_entry(item, nodes_payload)

        plan_id = new_plan_id()
        plan = Plan(
            plan_id=plan_id,
            goal_id=goal.goal_id,
            parent_run_id=parent_run_id,
            parent_task_id=parent_task_id,
            owner_id=goal.owner_id,
            revision=revision,
            status=PlanStatus.DRAFT,
            nodes=tuple(
                self._hydrate_node(schema, index, plan_id, goal)
                for index, schema in enumerate(nodes_payload)
            ),
            dependencies=tuple(
                Dependency(
                    dependency_id=new_dependency_id(),
                    plan_id=plan_id,
                    node_id=item["node_id"],
                    depends_on=item["depends_on"],
                )
                for item in dependency_payload
            ),
            budgets=goal.budgets,
            acceptance=CompletionCriteria(
                kind="structured_result_present",
                description=goal.success_criteria[:500],
            ),
        )
        validate_plan(plan, goal=goal)
        return plan

    # -- bounded model proposal request ------------------------------------------

    async def propose_plan_with_model(
        self, goal: Goal, interface_manager, *, provider_id: str, model_id: str,
        parent_run_id: str, parent_task_id: str, revision: int = 1,
    ) -> Plan:
        """Request one structure-constrained proposal through the InterfaceManager.

        The routing decision (provider and model) is made by trusted code; the
        model output is still untrusted and re-validated end to end.
        """
        prompt = (
            "Return only JSON with schema " + PLANNING_SCHEMA_VERSION + " for goal "
            + goal.goal_id + ". Constraints: at most "
            + str(goal.budgets.max_nodes) + " nodes; only tool "
            + DEFAULT_PLANNING_CAPABILITY + "; only these scopes: "
            + json.dumps(_scopes_payload(goal))
            + ". Dependencies must stay acyclic."
        )
        messages = [{"role": "user", "content": prompt}]
        collected: list = []
        async for chunk in interface_manager.stream_chat(provider_id, messages, model=model_id):
            collected.append(str(chunk))
        return self.build_plan_from_proposal(
            goal,
            "".join(collected),
            parent_run_id=parent_run_id,
            parent_task_id=parent_task_id,
            revision=revision,
        )

    # -- internals ---------------------------------------------------------------

    def _validate_dependency_entry(self, item, nodes_payload) -> None:
        if not isinstance(item, dict) or set(item) - {"node_id", "depends_on"}:
            raise ProposalRejected("A proposal dependency entry is malformed.")
        if not {"node_id", "depends_on"} <= set(item):
            raise ProposalRejected("A proposal dependency entry is malformed.")
        node_ids = {schema["node_id"] for schema in nodes_payload}
        if item["node_id"] not in node_ids or item["depends_on"] not in node_ids:
            # References must resolve inside this proposal; unknown nodes are
            # rejected before any graph analysis.
            raise ProposalRejected("A proposal dependency references an unknown node.")

    def _bounded_node(self, schema) -> bool:
        """Validate the bounded proposal node envelope before hydration."""
        if not isinstance(schema, dict) or set(schema) != {
            "node_id", "title", "required_capabilities", "payload",
            "data_scopes", "tool_scopes",
        }:
            return False
        if not _HEX32.fullmatch(str(schema.get("node_id", "")) or ""):
            return False
        title = schema.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            return False
        capabilities = schema.get("required_capabilities")
        if not isinstance(capabilities, list) or not capabilities or len(capabilities) > 20:
            return False
        if any(
            not isinstance(value, str) or not value or len(value) > 80 or any(ord(c) < 32 for c in value)
            for value in capabilities
        ):
            return False
        payload = schema.get("payload")
        if not isinstance(payload, dict):
            return False
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError):
            return False
        if len(encoded.encode("utf-8")) > 32768:
            return False
        data_scopes = schema.get("data_scopes")
        # At least one explicit data scope is required so a node can never be
        # scheduled with inherited or implicit data access.
        if not isinstance(data_scopes, list) or not data_scopes or len(data_scopes) > 10:
            return False
        for item in data_scopes:
            if not isinstance(item, dict) or set(item) != {
                "domain", "scope_type", "scope_id", "owner_id",
            }:
                return False
            if item.get("domain") not in {"conversation", "knowledge", "memory"}:
                return False
        tool_scopes = schema.get("tool_scopes")
        # Tool scopes may be empty: a tool-free agent is a legal candidate.
        if not isinstance(tool_scopes, list) or len(tool_scopes) > 10:
            return False
        for item in tool_scopes:
            if not isinstance(item, str) or not item or len(item) > 80:
                return False
        return True

    def _hydrate_node(self, schema, index: int, plan_id: str, goal: Goal) -> TaskNode:
        return TaskNode(
            node_id=str(schema["node_id"]),
            plan_id=plan_id,
            ordinal=index,
            title=str(schema["title"]).strip(),
            required_capabilities=tuple(schema["required_capabilities"]),
            acceptance=CompletionCriteria(
                kind="structured_result_present",
                description=goal.success_criteria[:500],
            ),
            payload=dict(schema["payload"]),
            data_scopes=tuple(
                DataScope(
                    domain=item["domain"],
                    scope_type=item["scope_type"],
                    scope_id=item["scope_id"],
                    owner_id=item["owner_id"],
                )
                for item in schema["data_scopes"]
            ),
            tool_scopes=tuple(schema["tool_scopes"]),
            status=NodeStatus.PENDING,
            max_retries=goal.budgets.max_retries_per_task,
        )

    def _parse_proposal_text(self, proposal_text) -> dict:
        """Parse bounded JSON out of a model or API proposal."""
        if not isinstance(proposal_text, str) or not proposal_text.strip():
            raise ProposalRejected("A plan proposal must be non-empty text.")
        if len(proposal_text) > _PROPOSAL_MAX_BYTES:
            raise ProposalRejected("A plan proposal exceeds its size budget.")
        candidate = proposal_text.strip()
        try:
            return dict(json.loads(candidate))
        except (TypeError, ValueError):
            # Tolerate fenced or lead-in prose: parse the outermost JSON object.
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                raise ProposalRejected("The proposal does not contain a JSON object.")
            try:
                return dict(json.loads(candidate[start:end + 1]))
            except (TypeError, ValueError) as exc:
                raise ProposalRejected("The proposal JSON could not be parsed.") from exc


def _scopes_payload(goal: Goal) -> list:
    return [
        {
            "domain": scope.domain,
            "scope_type": scope.scope_type,
            "scope_id": scope.scope_id,
            "owner_id": scope.owner_id,
        }
        for scope in goal.data_scopes
    ]


def _contains_plan_key(value) -> bool:
    if isinstance(value, dict):
        return bool(set(value.keys()) & _NESTED_PLAN_KEYS) or any(
            _contains_plan_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_plan_key(child) for child in value)
    return False


def _reject_nested_plan_fields(payload: dict) -> None:
    if any(key in _NESTED_PLAN_KEYS for key in payload):
        raise ProposalRejected("Recursive decomposition within a node payload is rejected.")
    if _contains_plan_key(payload):
        raise ProposalRejected("Recursive decomposition within a node payload is rejected.")
