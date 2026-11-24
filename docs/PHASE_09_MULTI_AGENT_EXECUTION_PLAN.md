# Phase 9 — Multi-Agent System and Specialized Agents

**Project:** Local AI Assistant  
**Phase:** 9 of 11  
**Document type:** Authoritative execution plan  
**Status:** Planned — execution contract prepared; no multi-agent execution is claimed  
**Dependencies:** Phases 6–8; Supervisor from Phase 7  
**Last reviewed:** 2026-11-24

## 1. Purpose and boundary

Expand from one bounded agent to multiple specialized agents collaborating through explicit, versioned contracts. The goal is controlled specialization and evidence-aware collaboration, not spawning arbitrary model instances or parallel prompts.

Agent Runtime remains the only lifecycle host. Supervisor owns coordination. PermissionManager owns authorization. ToolRuntime owns execution.

## 2. Current baseline and reuse

Reuse `core/agents/`, `core/orchestration/`, Conversation Agent, InterfaceManager, ContextManager, PermissionManager, ToolRuntime, and repositories. Do not introduce a second agent registry, task scheduler, or shared mutable global memory.

## 3. Scope

- Specialized agent definitions and version compatibility.
- Typed task assignment and isolated run contexts.
- Explicit handoff contracts and scoped shared state.
- Sequential collaboration as the first stable mode.
- Optional bounded concurrency after race/idempotency testing.
- Result comparison, evidence review, conflict and uncertainty reporting.
- Per-agent model capability constraints and permission isolation.
- Cost/time/tool budgets at both agent and parent-workflow levels.

## 4. Work packages

### WP-9.1 — Specialized agent contracts
Define agent roles, input/output schemas, capability requirements, data scopes, tool allowlists, and completion criteria. Validate all definitions at registration.
**Exit:** every specialized agent has a bounded responsibility and no implicit authority.

### WP-9.2 — Assignment and isolation
1. Bind each run to a unique agent-run subject.
2. Resolve grants for that exact run/role/scope.
3. Prevent inherited permissions unless explicitly delegated by the trusted owner.
4. Keep model-private memory isolated by default.
5. Define explicit shared artifacts and read/write ownership.
**Exit:** cross-agent access is denied unless a narrow grant exists.

### WP-9.3 — Sequential collaboration
1. Implement ordered task handoffs through Supervisor.
2. Validate handoff schema/version and size.
3. Persist sender/receiver run IDs and provenance.
4. Require receiver acknowledgment and defined failure behavior.
5. Preserve partial outputs and stop when required predecessor fails.
**Exit:** a multi-step workflow can complete with deterministic handoff history.

### WP-9.4 — Evidence and disagreement evaluation
1. Compare claims against source references and tool outcomes.
2. Preserve contradictory outputs rather than flattening them into consensus.
3. Distinguish independent evidence from duplicated model-generated claims.
4. Define adjudication/review states for unresolved disagreement.
5. Never use voting as a substitute for source verification.
**Exit:** aggregate results disclose disagreement and evidence gaps.

### WP-9.5 — Bounded concurrency
Only after sequential acceptance:
1. Add per-agent concurrency limits and queue semantics.
2. Add leases, cancellation propagation, idempotency keys, and duplicate-side-effect protection.
3. Define shared state locking/version conflicts.
4. Test race conditions, worker interruption, and recovery.
**Exit:** concurrent execution cannot duplicate writes or leak context.

### WP-9.6 — User controls and observability
Expose participating agents, task status, handoffs, model/provider use, budget consumption, approvals, and failures. Allow pause/cancel at parent and child level.
**Exit:** user can inspect and stop collaboration.

### WP-9.7 — Security and acceptance
Test cross-agent isolation, prompt injection in handoffs, malicious tool outputs, revoked grants, stale checkpoints, cancellation races, conflicts, and partial completion. Update docs and deliver a single phase PR.

## 5. Suggested implementation map

```text
core/agents/specialized/
core/orchestration/
  assignment.py
  handoffs.py
  aggregator.py
  concurrency.py
core/repositories/
tests/
  test_agent_isolation.py
  test_agent_handoffs.py
  test_agent_disagreement.py
  test_multi_agent_recovery.py
```

## 6. Required validation

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

CI uses fake agents/providers. Add deterministic tests for both sequential and concurrent paths, with explicit failure injection. Do not rely on live LLM agreement for correctness tests.

## 7. Phase-wide acceptance

- Each agent has a unique identity, version, bounded role, and completion criteria.
- Every run has isolated scopes and exact permissions.
- Handoffs are typed, validated, persisted, and provenance-preserving.
- Sequential collaboration is stable before concurrency is enabled.
- Conflicts, uncertainty, and missing evidence remain visible.
- Parent budgets, cancellation, and retries constrain all child runs.
- Tool access is exclusively through ToolRuntime.
- Full security/regression tests and docs pass.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 9 of 11 — Multi-Agent System and Specialized Agents

Execute WP-9.1 through WP-9.7 only after Phases 6–8 are accepted. Sequential collaboration is mandatory before concurrent collaboration. Do not treat multiple configured models as a Multi-Agent System.
