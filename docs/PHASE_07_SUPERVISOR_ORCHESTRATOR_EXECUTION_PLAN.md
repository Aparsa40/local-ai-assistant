# Phase 7 — Supervisor & Orchestrator

**Project:** Local AI Assistant  
**Phase:** 7 of 11  
**Document type:** Authoritative execution plan  
**Status:** Implementation correction in progress — PR #21 remains open; multi-task catalog routing and multi-agent fan-out are required before Phase 7 can be accepted  
**Dependencies:** Phase 6 Agent Runtime and at least one validated agent  
**Last reviewed:** 2026-11-25

## 1. Purpose and boundary

Implement a Supervisor as a specialized agent hosted by Agent Runtime. It decomposes complex goals into bounded tasks, tracks dependencies, assigns eligible agent roles, validates handoffs, aggregates results, and reports unresolved gaps.

The Supervisor is not the Agent Runtime, Permission Manager, Tool Runtime, or provider router. It must use the Phase 6 lifecycle and security boundaries.

## 2. Current baseline and reuse

Reuse `core/agents/` from Phase 6, `core/interface_manager.py`, `core/context/`, `core/permissions/`, `core/tools/runtime.py`, and repository/migration infrastructure. Do not create a second task/run lifecycle or invoke providers/tools directly.

## 3. Scope

- Supervisor agent definition and versioned planning contracts.
- Structured task decomposition and dependency graph.
- Canonical task catalog sourced from InterfaceManager model/operator profiles, with one deterministic primary route per task ID and explicit ordered fallbacks.
- Model capability profiles that distinguish primary specialties from overlapping secondary capabilities; overlap must never create duplicate task execution.
- Goal decomposition into one or more atomic task nodes, with every requested task accounted for before execution.
- Multi-agent fan-out: different task nodes in one goal may be assigned to different registered model-backed agents; a single node must never be marked covered by a union of agents unless it is explicitly decomposed into child nodes.
- Sequential execution is acceptable initially, but every planned node must be executed or explicitly marked blocked/failed; bounded parallel execution can follow after correctness tests.
- Typed handoff payloads with provenance and schema validation.
- Result aggregation, conflict/incomplete-result handling, and evidence coverage.
- Global budgets, deadlines, cancellation propagation, and stop conditions.
- Auditable assignment, handoff, retry, and aggregation events.

Out of scope: unrestricted autonomous planning, new provider adapters, user-facing conversation routing (Phase 8), and self-issued permissions. Multi-agent delegation across the registered, catalog-routed task agents is in scope and is mandatory in this phase.

## 4. Work packages

### WP-7.1 — Orchestration contract
1. Define Goal, Plan, TaskNode, Dependency, Assignment, Handoff, Evidence, and AggregateResult.
2. Require stable IDs, versions, parent run IDs, scope, deadlines, and acceptance criteria.
3. Define legal task states and dependency states.
4. Reject cyclic dependency graphs and unknown agent versions.
**Deliverable:** typed contracts and graph validator.
**Exit:** invalid plans cannot be persisted or scheduled.

### WP-7.2 — Dependency graph and scheduler
1. Implement a deterministic DAG representation.
2. Schedule only tasks whose dependencies are satisfied.
3. Enforce max active tasks, global wall-clock budget, per-task budgets, and retry limits.
4. Propagate cancellation and failure policy through dependent tasks.
5. Persist scheduler decisions and support restart recovery.
**Deliverable:** scheduler and tests.
**Exit:** no task starts early, twice, or after cancellation.

### WP-7.3 — Interface catalog task routing and assignment
1. Consume the InterfaceManager's persisted operator/model catalog; do not invent model capabilities or infer them from model names.
2. Normalize supported work into stable canonical task IDs (not free-form labels).
3. For each model, record evidence-backed primary specialties, secondary/overlapping capabilities, availability, and ordered fallback eligibility.
4. Each canonical task ID must resolve to exactly one primary route at a time; overlapping models are alternatives/fallbacks unless the plan explicitly requests independent review. This prevents duplicate or arbitrary execution.
5. Match each atomic task node to its primary registered model-backed agent and use only an eligible fallback when the primary is unavailable or fails under an explicit retry policy.
6. Treat unknown capability as unknown; do not infer from model names. Deny scope expansion beyond the parent run.
**Deliverable:** versioned task-route catalog and deterministic resolver with explainable primary/fallback decisions.
**Exit:** every task ID has a traceable route or an explicit uncovered-task result; no capability union can falsely qualify one executor.

### WP-7.4 — Goal decomposition and task planning
1. Decompose a compound goal into atomic task nodes using the canonical task IDs exposed by the InterfaceManager route catalog.
2. A model that owns multiple primary task IDs may receive multiple nodes; overlapping secondary capability does not create duplicate execution.
3. Preserve explicit dependencies between nodes and allow independent nodes to be fanned out to different agents.
4. Validate LLM-proposed plans against the route catalog, schemas, budgets, scopes, and DAG constraints; reject unknown or unrouted task IDs instead of silently dropping them.
5. Require application-side policy checks before plan acceptance; bound revisions and reject recursive decomposition loops.
6. Never let the Supervisor issue grants or approvals; model/tool calls remain behind InterfaceManager, ToolRuntime, and PermissionManager.
**Deliverable:** catalog-aware planner that accounts for every requested task and emits a complete executable DAG.
**Exit:** compound requests are split into all required atomic tasks, each with an explicit route, dependency, scope, and acceptance criterion.

### WP-7.5 — Multi-agent fan-out, handoff, and aggregation
1. Execute every ready task node through its catalog-selected registered agent; different nodes in one plan may use different agents/models.
2. Support bounded fan-out for independent nodes (sequential execution is a valid first implementation, but no node may be silently omitted).
3. Preserve agent/model/provider/run IDs, task-route ID, source references, evidence, and confidence semantics in handoffs.
4. Validate payload size/schema before persistence and enforce least-privilege grants independently for every child run.
5. Aggregate only after all required nodes reach a terminal state; expose contradictions, missing results, unavailable routes, and partial completion.
**Deliverable:** complete multi-agent execution path from plan DAG through child runs to aggregate response.
**Exit:** a compound goal cannot be reported complete unless every required task node completed and its result is represented in the aggregate.

### WP-7.6 — Recovery, cancellation, and audit
1. Resume interrupted plans from durable scheduler state.
2. Prevent duplicate task execution with leases/idempotency keys.
3. Enforce parent-child cancellation and deadline propagation.
4. Audit assignment, handoff, retries, and terminal decisions.
5. Add failure-injection and concurrency tests.
**Deliverable:** restart-safe orchestrator.
**Exit:** no duplicate side effect on replay and no orphaned active task.

### WP-7.7 — API, UI, and acceptance
Expose plan/run status and task graph read-only; allow explicit cancel and user review. Test DAG cycles, retries, partial failures, conflicting outputs, permission isolation, model unavailability, and recovery. Update docs and deliver one Phase 7 PR after CI passes.

## 5. Suggested implementation map

```text
core/orchestration/
  contracts.py
  graph.py
  planner.py
  scheduler.py
  assignment.py
  handoffs.py
  aggregator.py
  supervisor.py
core/repositories/
  orchestration_repository.py
tests/
  test_orchestration_graph.py
  test_orchestration_scheduler.py
  test_supervisor_assignment.py
  test_handoffs.py
  test_result_aggregation.py
```

## 6. Required validation

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

Run deterministic tests with fake agents/models; test persistence recovery and loopback API behavior. Do not require live cloud or hardware-intensive model calls for CI.

## 7. Phase-wide acceptance

- Plans are valid DAGs with explicit completion criteria and bounded budgets.
- Only registered Phase 6 agents can be assigned.
- Assignment respects evidence-backed task routes, primary/fallback policy, permission scope, and model availability.
- A compound request is decomposed into all required canonical task IDs; every task is assigned to its primary model-backed agent or an explicit eligible fallback.
- Overlapping model skills are resolved deterministically; no task is duplicated or omitted because of overlap.
- One agent's capabilities are never unioned with another's to claim a single node was executed; decomposition creates separate nodes and runs.
- Multi-agent results are collected and aggregated before the parent goal can be marked complete.
- Handoffs are typed, versioned, size-limited, and provenance-preserving.
- Aggregation exposes disagreement and incomplete evidence.
- Cancellation, retries, deadlines, and recovery are deterministic and auditable.
- Supervisor cannot bypass PermissionManager or ToolRuntime.
- Full tests and documentation match the implementation.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 7 of 11 — Supervisor & Orchestrator

Execute WP-7.1 through WP-7.7 in order after Phase 6. The Supervisor must run as an Agent Runtime agent; do not create a parallel runtime or treat LLM-generated plans as trusted commands.


## 9. Delivery record (2026-11-25)

**Status:** Existing implementation on branch `feat/phase-7-supervisor-orchestrator`; PR #21 targets `main` and remains open. The implementation is not Phase 7-complete until the required catalog-aware decomposition and multi-agent fan-out acceptance criteria above are met.

- **WP-7.1:** Typed Goal, Plan, TaskNode, Dependency, Assignment, Evidence, Handoff, AggregateResult, and bounded orchestration budgets; deterministic DAG validation, topological ordering, cycle detection, and explicit state transitions.
- **WP-7.2:** Persistence models, SQLite migration `0006_orchestration`, domain repository, sequential bounded scheduler, optimistic concurrency, retry limits, dependency skipping, cancellation, and reconciliation.
- **WP-7.3 (current partial):** Registered Phase 6 agent candidates only; explainable single-agent capability assignment, parent-scope containment, coarse InterfaceManager provider evidence, and exact per-run capability grants. The task-route catalog and model-backed primary/fallback assignment remain outstanding.
- **WP-7.4 (current partial):** Deterministic templates and bounded, schema-validated proposals exist, but deterministic templates are not catalog-aware and the current Supervisor run primarily records accepted plan bounds. Compound-goal task decomposition remains outstanding.
- **WP-7.5 (current partial):** Typed handoffs and plan-level aggregation exist for one agent per node. Full catalog-routed multi-agent fan-out and complete compound-task coverage remain outstanding.
- **WP-7.6:** Tests for DAG validation, scheduling, retries, dependency skipping, cancellation, wall-clock budgets, handoffs, aggregation, recovery, permission isolation, and assignment denial. A regression test additionally proves that capabilities declared by separate agents cannot be combined to qualify either agent.
- **WP-7.7:** Orchestration API endpoints in `main.py` and a minimal read-mostly status panel in `static/app.js`.
- **Documentation:** `docs/AGENT_RUNTIME.md`, `docs/AI_ORCHESTRATION.md`, `README.md`, and `CHANGELOG.md` updated.

**Known limitations:** Scheduling is sequential; dependency policy currently supports `all_success`; paused child runs require explicit resume or reconciliation; the UI is read-mostly; the hosted Supervisor run records plan acceptance rather than autonomously planning. Most importantly, the current one-agent-per-node resolver cannot yet route a compound goal across multiple model-backed agents from the InterfaceManager task catalog. This is a Phase 7 acceptance blocker, not a feature deferred to a new manager layer.

**Post-review correction:** Assignment eligibility requires one registered agent to declare the complete capability set for an atomic node. Partial capabilities distributed across multiple candidates are not combined. Compound work must be decomposed into separate atomic nodes and routed individually; simply denying the compound node is not sufficient Phase 7 behavior. The regression test is `test_assignment_requires_one_candidate_to_cover_all_capabilities`.

**Required validation:** `python -m compileall -q core main.py`, `python -m pytest -q -W default`, and `node --check static/app.js`. The pull request must remain unmerged until these checks pass and the review is complete.
