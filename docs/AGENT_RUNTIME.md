# Agent Runtime

**Status:** Phase 6 Agent Runtime and Phase 7 Supervisor/Orchestrator are implemented and merged (PR #19 and PR #21). Conversation Agent is Phase 8 planned work; broader multi-agent collaboration is Phase 9 planned work.

## 1. Purpose

Agent Runtime is the application-owned execution environment for goal-oriented agents. It manages agent registration, task execution, lifecycle, state, handoffs, and feedback loops.

It is not an LLM, a provider, or a model router. An agent may use an online LLM, a local LLM, deterministic application logic, or a hybrid of these.

## 2. Core distinction

- **LLM:** a reasoning and generation engine that receives input and returns output.
- **Agent:** a goal-oriented execution unit with a defined responsibility, state, permitted capabilities, and a controlled execution loop.
- **Agent Runtime:** the infrastructure that hosts and controls agents.
- **Supervisor Agent:** a specialized agent that plans and coordinates work across tasks or other agents.
- **Multi-Agent System:** multiple agents with explicit responsibilities and controlled communication/handoffs.

A module is not automatically an agent. It qualifies as an agent when it owns a goal-oriented workflow and can manage its execution state and completion criteria. Ordinary infrastructure services remain services.

## 3. Runtime responsibilities

- Agent Registry: register agent types, versions, contracts, and enabled state.
- Lifecycle Manager: create, start, pause, resume, cancel, and finish agent runs.
- Task Manager: represent goals, subtasks, dependencies, deadlines, and completion criteria.
- State Manager: persist run state and checkpoints so eligible work can resume.
- Context Builder: provide only the context authorized and needed for the task.
- Execution Controller: run bounded plan/act/observe/evaluate cycles.
- Tool Access Gateway: expose tools through the permission and execution boundary.
- Handoff Manager: pass structured task results between agents.
- Run Evaluator: determine whether acceptance criteria are met, more work is needed, or the run must stop.
- Audit/Event Recorder: retain decisions, tool activity, model/provider identity, failures, and outcomes.

## 4. Agent contract

Each agent definition should specify:

| Field | Meaning |
| --- | --- |
| agent_id | Stable identifier |
| version | Version of the agent workflow/contract |
| goal | Responsibility and intended outcome |
| input_schema | Required task input |
| output_schema | Expected structured result |
| completion_criteria | Conditions for success |
| allowed_models | Model roles or capability requirements, not hard-coded vendor names |
| allowed_tools | Tool IDs that may be requested |
| data_scopes | Explicitly permitted context and knowledge scopes |
| max_iterations | Bounded execution limit |
| approval_policy | Actions requiring user confirmation |

An agent definition describes what the agent is allowed and expected to do. It does not itself grant permissions.

## 5. Execution lifecycle

1. Receive a task with a stable run ID.
2. Validate the agent definition and input schema.
3. Resolve task context through permission-aware services.
4. Select an execution strategy and eligible model, if language reasoning is required.
5. Produce or update a bounded plan.
6. Request an action or tool call.
7. Validate the proposed action and check permissions in application code.
8. Execute only authorized actions.
9. Observe the result and update run state.
10. Evaluate completion criteria.
11. Continue, hand off, request user input/approval, or stop.
12. Persist the final result and audit trail.

The model proposes reasoning and actions. Runtime code enforces schemas, iteration limits, permissions, execution, state transitions, and stop conditions.

## 6. Online and offline execution

Agent Runtime must not depend on a cloud provider.

- Online inference is accessed through Interface Manager and eligible cloud-provider adapters.
- Offline inference is accessed through Interface Manager and local-provider adapters such as Ollama.
- Deterministic agents may run without any LLM.
- The same agent contract should work with different eligible models where capability requirements are met.
- Switching engines must preserve the task input, authorized context, and checkpoint state. It must not assume two models have identical capabilities or context windows.
- A cloud-to-local fallback must never send private local data to a cloud provider.
- If no eligible local model is available, the run must pause or report the limitation rather than claim success.

## 7. Security boundaries

- Agent definitions are not permission grants.
- Model-generated tool calls are proposals, not authorization.
- Every protected read or write is checked by the Permission Manager.
- Tool execution occurs only through Tool Runtime.
- Agents receive least-privilege, task-scoped context.
- Secrets are never placed in prompts or ordinary task logs.
- External content and model output are untrusted until validated.
- Destructive or externally visible actions require explicit approval according to policy.

## 8. Supervisor and Multi-Agent boundary

The Supervisor is an agent hosted by Agent Runtime; it is not the Runtime itself.

Initially, one agent should complete a bounded workflow end to end. Multi-Agent orchestration is introduced only after single-agent execution, state persistence, permission enforcement, cancellation, and evaluation are reliable.

For multi-agent runs:
- each agent receives a scoped task and explicit acceptance criteria;
- handoffs use versioned structured outputs;
- shared state is mediated by runtime services;
- agents cannot silently expand one another's permissions;
- disagreement and incomplete results remain visible;
- the Supervisor coordinates but does not bypass validation or security boundaries.

## 9. Initial implementation sequence

1. Define agent/task/run contracts and deterministic lifecycle management.
2. Add a single bounded agent with no autonomous external side effects.
3. Add model-backed planning and tool proposals through Interface Manager.
4. Add permissioned Tool Runtime and resumable checkpoints.
5. Add the Supervisor and orchestration baseline (implemented in Phase 7).
6. Integrate user-facing Conversation Agent in Phase 8, then expand specialized-agent collaboration in Phase 9.

Items 1, 2, 3 (route allowlist and transmission authorization), and 4 are implemented in Phase 6. The Supervisor/orchestration baseline (item 5) is implemented in Phase 7. Conversation Agent integration is Phase 8; broader multi-agent collaboration remains Phase 9.

## 10. Non-goals for the first version

- No unrestricted autonomous computer control.
- No self-granting permissions.
- No unbounded recursive planning or tool loops.
- No mandatory cloud model.
- No assumption that every application module must become an agent.
- No multi-agent complexity before a single-agent workflow is testable.

## 11. Phase 6 implementation record

Phase 6 delivered the bounded, application-owned Agent Runtime. Phase 7 subsequently added the Supervisor/Orchestrator baseline on that runtime and merged it via PR #21. Conversation Agent, broader multi-agent collaboration and AI Librarian workflows are not implemented yet (Phases 8, 9 and 10 respectively).

Implemented components (branch `feat/phase-6-agent-runtime`):

- `core/agents/contracts.py`: immutable `AgentDefinition`, `AgentTask`, `AgentRun`, `AgentBudgets`, `AgentCheckpoint`, `RunEvent`, `CompletionCriteria`, and `DataScope` contracts; the allowed `TRANSITIONS` table with terminal absorbing states; bounded schema and payload validation.
- `core/agents/registry.py`: trusted registry over persisted definitions; unknown and disabled versions are rejected; returned definitions are deep copies.
- `core/agents/lifecycle.py`: deterministic create/start/pause/resume/cancel/complete/fail transitions with keyword-only `expected_version` optimistic concurrency, one in-process executor claim per run, truthful pause and failure stop reasons, approval-pointer gating, and `recover_stale_runs()` restart recovery that pauses orphaned runs with error code `restart_recovery` instead of silently re-executing them.
- `core/agents/context.py`: permission-checked context assembly through the PermissionManager, explicit knowledge `DataScope` resolution, least-privilege `CapabilityBinding` as plain data (no handlers, sessions, or credentials; Phase 6 supports read-only bindings only), and exact per-run grants issued by the trusted local owner.
- `core/agents/controller.py`: bounded plan/act/observe/evaluate loop enforcing iteration, wall-clock, tool-call, input-byte, output-byte, and model-token budgets; run-identity and scope validation of every tool proposal; model invocation exclusively through the InterfaceManager, gated by the `allowed_models` route list and an explicit task-level `allow_model_transmission` authorization; checkpoints before externally visible transitions; structured outcomes with truthful completion reporting.
- `core/agents/events.py`: append-only, redacted run event recorder using a safe metadata whitelist and secret-pattern redaction.
- `core/agents/builtins.py`: one builtin agent, `knowledge-analyzer` 1.0.0, a deterministic read-only knowledge scope analysis workflow with no model dependency on its happy path.
- `core/agents/bootstrap.py`: composition root owning the single trusted registry activation path and the application ToolRegistry, including the read-only `knowledge_search` 1.0.0 tool with bounded input/output; `LocalOwnerGrantAdministrationPolicy` scopes grant administration to the local owner while everything else stays default-deny.
- `core/repositories/`: `AgentDefinitionRepository`, `AgentTaskRepository`, and run/event/checkpoint repositories with explicit transaction boundaries.
- `main.py`: loopback- and same-origin-protected endpoints for listing definitions, inspecting runs and redacted events, creating tasks, and executing, pausing (including approval handoff), resuming, and cancelling runs; startup registers builtin agents and performs restart recovery.
- `static/`: a minimal run-status and approval-handoff view.

Persistence: migration `0005_agent_runtime` adds the agent definition, task, run, checkpoint, and run-event tables; migrations remain ordered and idempotent.

Tests: `tests/agent_test_models.py` (full composed environment over a private SQLite file), `tests/test_agent_contracts.py`, `tests/test_agent_registry.py`, `tests/test_agent_lifecycle.py`, `tests/test_agent_execution.py`, and `tests/test_agent_permissions.py` cover contract validation, registry trust, the full transition matrix, concurrency conflicts, event-persistence failure surfacing, restart recovery, every budget class, permission denial paths (run identity, scope binding, capability binding, mutating-tool rejection, issuer identity), grant least privilege, and model unavailability.

Validation status: GitHub Actions successfully ran Python compilation, frontend syntax validation, and the test suite on the final Phase 6 head `bdf4e01dd593a860d9efb245f533c019c857ef17` for both push and pull-request events before PR #19 merged. A local Windows loopback HTTP smoke test remains a separate environment-level check.

Known limitations: one bounded builtin agent; no Supervisor, Conversation Agent, multi-agent, autonomous publishing, credential access, or unrestricted execution; capability bindings are read-only by design for this phase; cloud/model routing and response composition remain future work.

Related: AI_ORCHESTRATION.md, INTERFACE_MANAGER.md, PERMISSIONS.md, ARCHITECTURE.md.

## 12. Phase 7 implementation record (Supervisor and Orchestrator)

Phase 7 adds a bounded Supervisor and orchestration layer as a specialized
registered agent hosted by the existing Phase 6 Agent Runtime. It introduces
no second run lifecycle, no parallel execution engine, no provider router, and
no separate permission system.

Implemented components (branch `feat/phase-7-supervisor-orchestrator`):

- `core/orchestration/contracts.py` (WP-7.1): typed, versioned contracts for
  `Goal`, `Plan`, `TaskNode`, `Dependency`, `Assignment`, `Handoff`, `Evidence`,
  and `AggregateResult`, with stable 32-character identifiers, parent run
  references, explicit data/tool scopes, bounded budgets, and acceptance
  criteria. Legal node and dependency states use explicit transition tables;
  anything else is rejected. Untrusted input cannot inject identifiers,
  wildcards, control characters, or oversized payloads.
- `core/orchestration/graph.py`: deterministic graph validator and topological
  ordering. Cycles, duplicate or dangling references, node budget violations,
  cross-plan references, and scope expansion beyond the parent goal are all
  rejected before any plan is persisted or scheduled.
- `core/orchestration/models.py` and migration `0006_orchestration` (WP-7.2):
  goal, plan, node, dependency, assignment, handoff, and event records. Plans
  and nodes carry an optimistic-concurrency `version`; assignments, handoffs,
  and events are append-only.
- `core/repositories/orchestration_repository.py` (WP-7.2): persistence
  adapters with atomic plan/node/dependency creation, `transition(expected_version)`
  optimistic updates for plans and nodes, and append-only assignment, handoff,
  and event repositories.
- `core/orchestration/scheduler.py` (WP-7.2): deterministic sequential
  scheduler. It schedules only PENDING nodes whose prerequisites are COMPLETED,
  prevents duplicate node execution, enforces plan wall-clock budgets, retry
  limits, and explicit failure/cancellation propagation, persists every
  scheduling decision, and supports restart recovery via
  `reconcile_plan()` (a SCHEDULED node without a child run returns to PENDING;
  a child run that already finished maps its truthful terminal outcome without
  re-execution). Child tasks and runs are created exclusively through
  `AgentLifecycleManager` and executed exclusively through the existing
  `ExecutionController`; no direct tool or provider call exists anywhere in
  the scheduler.
- `core/orchestration/assignment.py` (WP-7.3): deterministic, explainable
  capability matching over registered agent candidates only. Tool evidence
  comes from the trusted `ToolRegistry` catalog; model evidence comes only
  through `InterfaceManager.list_providers()`. Unknown capabilities stay
  unknown, capabilities are never inferred from model names, requested scopes
  beyond the parent goal are denied, and every decision records bounded
  reasons and evidence.
- `core/orchestration/handoffs.py` (WP-7.5): versioned `orchestration.handoff/1`
  handoff envelopes with size validation and bounded degradation.
- `core/orchestration/aggregator.py` (WP-7.5): deterministic aggregation into
  `completed`, `partial`, `failed`, or `cancelled` aggregates that surface
  conflicts and missing evidence instead of resolving them silently.
- `core/orchestration/planner.py` (WP-7.4): `PlanningService` supporting
  deterministic template plans (one bounded node per goal data scope) and
  bounded, schema-validated LLM proposals (`orchestration.proposal/1`).
  Proposals are byte-limited, reject nested plan fields (recursive
  decomposition), are revalidated end to end, and revisions are bounded
  (`max_plan_revisions = 2`). Model requests go exclusively through the
  InterfaceManager.
- `core/orchestration/supervisor.py` (WP-7.4): the `supervisor` agent
  1.0.0 with zero model tokens, zero tool calls, and a deterministic
  `decide()` that reports the accepted plan's bounds truthfully, plus the
  trusted `OrchestrationService` composition root (`create_goal`, `plan_goal`,
  `execute_plan`, `cancel_plan`, `reconcile`, read-only `plan_view`).
  Planning always happens beneath a real hosted supervisor run so plan
  references are traceable.
- `core/agents/bootstrap.py`: idempotent supervisor definition and behavior
  registration, trusted capability-candidate registration, and
  `build_orchestration(db)`.
- `main.py` (WP-7.7): loopback- and same-origin-protected read/write-bound
  orchestration endpoints `POST /api/orchestration/goals`,
  `POST /api/orchestration/plans`, `POST /api/orchestration/plans/{plan_id}/execute`,
  `POST /api/orchestration/plans/{plan_id}/cancel`,
  `POST /api/orchestration/plans/{plan_id}/reconcile`,
  `GET /api/orchestration/plans`, and `GET /api/orchestration/plans/{plan_id}`.
- `static/`: a minimal orchestration panel inside the agents tab (goal/plan
  creation, execution, cancellation, reconciliation, and a read-only plan
  detail view with assignments).

Security boundaries preserved: the Supervisor issues no grants or approvals;
it never reaches the PermissionManager, the ToolRuntime, or a provider
directly. Model calls flow through the InterfaceManager only; tool calls flow
through ToolRuntime with PermissionManager authorization; persisted state
uses the existing repository and migration infrastructure.

Tests: `tests/test_orchestration_supervisor.py` covers planning templates and
proposal validation (schema, cycles, dangling references, nested plan fields,
revision cap, wrong owner), scheduler execution through the real Agent
Runtime, dependency ordering without early or duplicate execution, assignment
denial (no candidates, unknown capability, scope expansion, missing provider
evidence for model-dependent candidates), failure injection with bounded
retries and dependent skipping, wall-clock budget failure, cancellation
propagation, and restart recovery without duplicated side effects.

Known limitations: scheduling is strictly sequential in Phase 7
(`max_active_tasks` is honored as one concurrent execution); the
coordination loop is trusted application code while the supervisor agent run
documents the accepted plan; a paused child run keeps its node RUNNING until
an explicit resume/reconcile, it is not auto-resumed; only the `all_success`
dependency policy is supported; and every model call must still pass the
task-level transmission authorization from Phase 6.
