# Phase 6 — Agent Runtime

**Project:** Local AI Assistant  
**Phase:** 6 of 11  
**Document type:** Authoritative execution plan  
**Status:** Implemented on `feat/phase-6-agent-runtime` (WP-6.1 through WP-6.8); one pull request pending review and CI; not merged  
**Dependencies:** Phase 4 Storage/Repositories/Conversation/Memory/Context/Knowledge; Phase 5 Permission Manager/Tool Runtime  
**Last reviewed:** 2026-11-24

## 1. Purpose and boundary

Implement the application-owned execution environment for bounded goal-oriented agents. Agent Runtime owns agent definitions, task/run lifecycle, checkpoints, cancellation, execution budgets, scoped context, tool invocation through ToolRuntime, and completion evaluation.

It is not a model provider, model router, Supervisor, Conversation Agent, or a synonym for every service. Agents may use LLMs, deterministic application code, or a hybrid.

## 2. Current baseline and dependencies

Reuse, do not duplicate:
- Provider-neutral inference: `core/interface_manager.py` and `core/providers/`.
- Local model lifecycle: `core/runtime/`; Agent Runtime must not call Ollama endpoints directly.
- Persistence: `core/storage/`, `core/repositories/`, and SQLite versioned migrations in `core/migrations/`.
- Conversation and context: `core/conversations/`, `core/context/`, `core/memory/`, `core/knowledge/`.
- Authorization/execution: `core/permissions/` and `core/tools/runtime.py`.
- Existing UI/API composition: `main.py` and `static/`.

Phase 5 operational grant/approval integration is a prerequisite. Do not expose agent runs until Knowledge access is mediated, grant/approval administration is usable, and destructive actions fail closed.

## 3. Scope

### In scope
- Versioned AgentDefinition, AgentInput, AgentOutput, Task, Run, Step, Checkpoint, and CompletionCriteria contracts.
- Explicit AgentRegistry with trusted application registration only.
- Persistent task/run lifecycle and deterministic state transitions.
- Bounded execution controller with iteration, time, token, tool-call, and output budgets.
- Pause, resume, cancel, timeout, failure, and completion behavior.
- Explicit context scopes and least-privilege tool capability declarations.
- Model calls through InterfaceManager and tool calls through ToolRuntime.
- Trace IDs, audit events, structured outcomes, and resumable checkpoints.
- One initial deterministic or model-assisted agent with no autonomous external side effects.

### Out of scope
- Supervisor decomposition and multi-agent coordination (Phase 7/9).
- User-facing Conversation Agent (Phase 8).
- Automatic document ingestion/publication (Phase 10).
- General computer control, unrestricted shell, arbitrary Python, or unrestricted network access.
- Self-granting permissions or implicit cloud fallback.

## 4. Work packages and order

### WP-6.1 — Runtime contract and threat review
1. Define immutable contracts and allowed lifecycle transitions.
2. Define stable agent IDs and semantic versions.
3. Define input/output schema limits and completion criteria.
4. Define task ownership, scope, cancellation semantics, and idempotency.
5. Threat-model prompt injection, tool output, replay, stale checkpoints, and concurrent resume.
**Deliverable:** typed contracts and transition table.
**Exit:** invalid transitions, unknown agent versions, and untrusted agent metadata are rejected.

### WP-6.2 — Persistence and repositories
1. Define agent definitions, tasks, runs, run events, and checkpoints.
2. Add ordered SQLite migration revisions; never rely on `create_all()` for existing-table evolution.
3. Implement domain repositories with explicit transaction boundaries.
4. Preserve checkpoint history and current-run state separately.
5. Add optimistic concurrency/version checks for resume and cancellation.
**Deliverable:** migrations, repositories, and persistence tests.
**Exit:** restart/reload restores a consistent run without duplicate execution.

### WP-6.3 — Agent Registry and lifecycle manager
1. Register versioned definitions from trusted application code.
2. Validate schemas and capability declarations at registration.
3. Implement create/start/pause/resume/cancel/complete/fail transitions.
4. Enforce one active executor per run.
5. Reject disabled or unknown definitions.
**Deliverable:** registry and lifecycle service.
**Exit:** lifecycle transitions are deterministic and auditable.

### WP-6.4 — Scoped context and capability binding
1. Resolve owner/task/conversation scopes explicitly.
2. Build context through ContextManager and KnowledgeService only after PermissionManager checks.
3. Bind the run subject to exact tool/resource grants.
4. Never pass database sessions, repositories, provider credentials, or filesystem roots to an agent.
5. Keep local-private context out of cloud requests unless the user explicitly authorizes the destination.
**Deliverable:** RunContextBuilder and capability resolver.
**Exit:** cross-owner/scope tests deny access.

### WP-6.5 — Bounded execution controller
1. Implement deterministic plan/act/observe/evaluate loop.
2. Enforce max iterations, wall-clock deadline, tool calls, input/output bytes, and model token budget.
3. Call models through InterfaceManager using normalized request/response contracts.
4. Validate every tool proposal against registry and execute only through ToolRuntime.
5. Persist checkpoint before/after externally visible state transitions.
6. Pause on approval-required actions; never auto-approve.
**Deliverable:** ExecutionController and one minimal agent.
**Exit:** a bounded task finishes or stops with a truthful reason and resumable state.

### WP-6.6 — API and UI lifecycle surface
1. Add loopback-protected endpoints to list definitions and inspect/create runs.
2. Add explicit pause/resume/cancel operations; GET remains read-only.
3. Expose progress and safe event summaries, not private prompts/secrets.
4. Add minimal UI for run status and user approval handoff.
**Deliverable:** API schemas and UI status view.
**Exit:** a user can inspect and safely stop a run without direct database access.

### WP-6.7 — Initial agent and regression
1. Implement one low-risk agent, preferably a deterministic knowledge/conversation analysis task.
2. No autonomous publishing, deletion, credential access, or external transmission.
3. Test lifecycle, restart recovery, concurrent resume, cancellation, budgets, permissions, audit failure, model unavailability, and tool denial.
4. Run full suite, compile, frontend syntax, and API smoke tests.
**Deliverable:** one usable bounded agent and validation report.
**Exit:** all runtime and security invariants pass.

### WP-6.8 — Documentation and delivery
Update Agent Runtime contract, architecture, roadmap, API reference, README, and this plan. Record exact migrations, CI checks, and known limits. Deliver one branch/PR for Phase 6 unless review/CI size requires a documented split. Merge only after checks pass and explicit user authorization.

## 5. Suggested implementation map

```text
core/agents/
  contracts.py
  registry.py
  lifecycle.py
  controller.py
  context.py
  checkpoints.py
  evaluator.py
  events.py
core/repositories/
  agent_repository.py
  task_repository.py
  run_repository.py
core/database.py
core/migrations/
tests/
  test_agent_contracts.py
  test_agent_lifecycle.py
  test_agent_controller.py
  test_agent_recovery.py
  test_agent_permissions.py
```

Adapt the exact layout to existing repository conventions; do not create empty placeholder modules.

## 6. Required validation

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

Also run focused agent tests and loopback HTTP smoke tests. Verify restart recovery against a temporary SQLite file. Hardware-intensive Ollama loading is not required; model calls should use fakes in deterministic tests.

## 7. Phase-wide acceptance

- Agent definitions are versioned, validated, and registered only by trusted code.
- Tasks/runs have stable IDs, durable state, checkpoints, and legal transitions.
- Execution is bounded by explicit budgets and supports pause/resume/cancel.
- Context is explicit, scoped, permission-checked, and provenance-preserving.
- Every tool invocation goes through ToolRuntime and PermissionManager.
- No self-grant, implicit scope expansion, unsafe retry, or silent cloud egress.
- One agent completes a real bounded workflow and reports incomplete work honestly.
- Full tests, migrations, docs, and CI evidence agree.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 6 of 11 — Agent Runtime

This is the authoritative execution plan for Phase 6. Execute WP-6.1 through WP-6.8 in order, after Phase 5 acceptance. Do not implement Supervisor, Conversation Agent, or Multi-Agent behavior in this phase. Do not claim a general autonomous agent platform after implementing only a single bounded workflow.

## 9. Delivery record (2026-11-24)

Recorded during delivery on branch `feat/phase-6-agent-runtime`; the branch is not merged.

- **WP-6.1 / WP-6.2:** typed immutable contracts, the allowed `TRANSITIONS` table with terminal absorbing states, ordered migration `0005_agent_runtime` (agent definitions, tasks, runs, run events, checkpoints), and domain repositories with optimistic-concurrency transitions.
- **WP-6.3:** trusted `AgentRegistry` and `AgentLifecycleManager` with one executor claim per run, truthful stop reasons, approval-pointer gating, and `recover_stale_runs()` restart recovery (orphans are paused with error code `restart_recovery`, never silently re-executed).
- **WP-6.4:** permission-checked context assembly through the PermissionManager, explicit knowledge `DataScope` resolution, least-privilege read-only `CapabilityBinding`, and exact per-run grants issued by the trusted local owner (agent subjects can never administer permissions).
- **WP-6.5:** `ExecutionController` bounded by iteration, wall-clock, tool-call, input-byte, output-byte, and model-token budgets; model calls exclusively through InterfaceManager with an `allowed_models` route check and explicit task-level `allow_model_transmission` authorization; every tool proposal validated and executed only through ToolRuntime; checkpoints before externally visible transitions; truthful outcomes.
- **WP-6.6:** loopback- and same-origin-protected agent endpoints (list definitions, inspect runs and redacted events, create tasks, execute, pause with approval handoff, resume, cancel) wired at startup with builtin registration and restart recovery; minimal run-status UI.
- **WP-6.7:** builtin deterministic agent `knowledge-analyzer` 1.0.0 (read-only `knowledge_search` tool over one bound scope), plus regression suites in `tests/agent_test_models.py`, `tests/test_agent_contracts.py`, `tests/test_agent_registry.py`, `tests/test_agent_lifecycle.py`, `tests/test_agent_execution.py`, and `tests/test_agent_permissions.py`; the existing `tests/test_knowledge_storage.py` revision assertions were updated for `0005_agent_runtime`.
- Two focused fixes were required while composing the tests and are committed separately: `fix(agents): wire the local owner grant administration policy into bootstrap` and `fix(agents): allow run attempt updates in the run field whitelist`.
- **WP-6.8:** this plan, `docs/AGENT_RUNTIME.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/README.md`, `README.md`, and `CHANGELOG.md` updated; migration `0005_agent_runtime` recorded; known limits recorded in [AGENT_RUNTIME.md](AGENT_RUNTIME.md#11-phase-6-implementation-record).

Validation and environment limitation: the authoring environment for the final work packages was web-only (no Python or Node runtime), so `python -m compileall -q core main.py`, `python -m pytest -q`, `node --check static/app.js`, and the loopback HTTP smoke tests could not be executed while authoring. They run in CI on the pull request, and CI evidence must pass before any merge. There is no dedicated API_REFERENCE.md in this repository; the agent endpoints are documented in [AGENT_RUNTIME.md](AGENT_RUNTIME.md#11-phase-6-implementation-record).

Known limits after this phase: exactly one bounded builtin agent; read-only capability bindings only; no Supervisor, Conversation Agent, multi-agent, or AI Librarian behavior; no autonomous publishing, deletion, credential access, or unrestricted execution.
