# Phase 7 — Supervisor & Orchestrator

**Project:** Local AI Assistant  
**Phase:** 7 of 11  
**Document type:** Authoritative execution plan  
**Status:** Planned — execution contract prepared; no Supervisor implementation is claimed  
**Dependencies:** Phase 6 Agent Runtime and at least one validated agent  
**Last reviewed:** 2026-11-24

## 1. Purpose and boundary

Implement a Supervisor as a specialized agent hosted by Agent Runtime. It decomposes complex goals into bounded tasks, tracks dependencies, assigns eligible agent roles, validates handoffs, aggregates results, and reports unresolved gaps.

The Supervisor is not the Agent Runtime, Permission Manager, Tool Runtime, or provider router. It must use the Phase 6 lifecycle and security boundaries.

## 2. Current baseline and reuse

Reuse `core/agents/` from Phase 6, `core/interface_manager.py`, `core/context/`, `core/permissions/`, `core/tools/runtime.py`, and repository/migration infrastructure. Do not create a second task/run lifecycle or invoke providers/tools directly.

## 3. Scope

- Supervisor agent definition and versioned planning contracts.
- Structured task decomposition and dependency graph.
- Capability-based agent selection using declared, verified capabilities.
- Sequential task scheduling first; bounded concurrency only after correctness tests.
- Typed handoff payloads with provenance and schema validation.
- Result aggregation, conflict/incomplete-result handling, and evidence coverage.
- Global budgets, deadlines, cancellation propagation, and stop conditions.
- Auditable assignment, handoff, retry, and aggregation events.

Out of scope: unrestricted autonomous planning, multi-agent collaboration beyond registered Phase 6 agents, new provider adapters, user-facing conversation routing (Phase 8), and self-issued permissions.

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

### WP-7.3 — Capability-based assignment
1. Define agent capability declarations and evidence levels.
2. Match required capabilities to registered agent definitions.
3. Consider model capability/availability only through InterfaceManager evidence.
4. Treat unknown capability as unknown; do not infer from model names.
5. Deny assignments whose requested data/tool scopes exceed the parent run.
**Deliverable:** deterministic assignment resolver.
**Exit:** assignment is explainable and least-privilege.

### WP-7.4 — Planning strategy
1. Begin with deterministic templates and structured LLM proposals.
2. Validate LLM-produced plans against schemas, budgets, allowed agent IDs, and dependency graph constraints.
3. Require application-side policy checks before plan acceptance.
4. Bound plan revisions and reject recursive decomposition loops.
5. Never let the Supervisor issue grants or approvals.
**Deliverable:** planning service.
**Exit:** model output cannot expand authority or exceed budgets.

### WP-7.5 — Handoff and aggregation
1. Define versioned input/output handoff envelopes.
2. Preserve agent/run IDs, source references, evidence, and confidence semantics.
3. Validate payload size/schema before persistence.
4. Aggregate by explicit acceptance criteria, not majority vote or stylistic similarity.
5. Surface contradictions, missing evidence, and partial completion.
**Deliverable:** HandoffManager and ResultAggregator.
**Exit:** every aggregate is traceable to contributing runs and unresolved conflicts remain visible.

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
- Assignment respects capability evidence, permission scope, and model availability.
- Handoffs are typed, versioned, size-limited, and provenance-preserving.
- Aggregation exposes disagreement and incomplete evidence.
- Cancellation, retries, deadlines, and recovery are deterministic and auditable.
- Supervisor cannot bypass PermissionManager or ToolRuntime.
- Full tests and documentation match the implementation.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 7 of 11 — Supervisor & Orchestrator

Execute WP-7.1 through WP-7.7 in order after Phase 6. The Supervisor must run as an Agent Runtime agent; do not create a parallel runtime or treat LLM-generated plans as trusted commands.
