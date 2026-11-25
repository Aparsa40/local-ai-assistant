# Changelog

All notable changes are documented here. The project follows Semantic Versioning.

## Unreleased

### Added (Phase 8 — Conversation Agent, implementation branch feat/phase-8-conversation-agent, under review)
- Versioned Conversation Agent contracts in `core/conversation_agent/contracts.py`: ConversationRequest, DispatchDecision, ResponseCandidate, ValidationReport, Provenance, and a versioned SSE ConversationEvent envelope with whitelisted payload redaction.
- Deterministic, conservative dispatcher (`dispatcher.py`): direct response, registered deterministic workflows, explicit agent delegation, needs-user-input, and blocked routes; an advisory model classifier, when configured, may only move ordinary questions to needs-user-input, and malformed, failing, or unavailable classification falls back deterministically. Classification never grants permissions or selects destinations.
- Destination and egress authorization (`egress.py`), separate from retrieval authorization: local Ollama is a local destination; cloud adapters never receive memory/knowledge-scope content unless the user explicitly authorized private-context egress for that request; fail-closed when the whole payload would be private.
- Normalized online/offline strategies through the InterfaceManager only (`strategies/`), with evidenced local-readiness probing, output budgets and mid-stream cancellation checkpoints. Cloud fallback is disabled by default; an explicitly configured fallback must pass destination/egress checks and is disclosed as a partial outcome.
- Bounded delegation through the existing Phase 7 OrchestrationService composition root (`orchestration_gateway.py`): child scopes are constrained to the request scope, correlation is preserved, cancellation propagates to the Phase 7 plan, and partial/failed/cancelled orchestration is reported truthfully.
- Response validator and composer: valid/partial/rejected states, fabricated-reference detection against retrieved context, delegated task-coverage and terminal-state checks, and truthful limitation text.
- Durable conversation lifecycle with SQLite migration `0007_conversation_operations`: request hashes and safe lifecycle events survive restart; completed requests replay, interrupted operations are marked uncertain and are never automatically re-executed; duplicate keys cannot be reused with different messages. The bounded registry also supports disconnect-safe leaders, explicit cancellation via POST /api/chat/cancel, same-key retry after interrupted SSE streams, and wall-clock/output budgets.
- POST /api/chat migrated to the new lifecycle with a backward-compatible request schema (extended with optional idempotency and scope fields). Memory and Knowledge context services are wired through the existing PermissionManager adapters, scope ownership comes from trusted AccessContext, and the Alpine.js UI supports explicit cancellation and same-request retry.

### Phase 8 acceptance status
- Latest verified approval-handoff revision: 475 Python tests passed in 24.52s; compileall and JavaScript syntax validation passed in CI run `45702808736` (commit `0da8e313`).
- Delegated Agent Runtime tool approvals now flow through `approval_required` SSE events and actionable chat UI controls; approval decisions resume the same child run and reconcile the existing plan without re-execution.
- Memory/knowledge context approvals now create request-bound approval requests, emit actionable SSE events, and consume the approved action exactly once before retrieval resumes. Remaining before phase acceptance: deterministic workflow routes remain fail-closed until an owning service registers a real workflow; model-assisted classification remains optional/off by default; real local loopback smoke remains outstanding.

### Documentation — Phase 8 preparation (2026-11-25)
- Rewrote the Phase 8 Conversation Agent execution plan as an implementation and acceptance contract covering request identity, deterministic dispatch, explicit context/egress authorization, online/offline strategy parity, Supervisor handoff, response validation, SSE lifecycle, idempotency, cancellation, recovery, UI migration and test strategy.
- Reconciled Phase 7 status with merged PR #21 and documented the boundary between the delivered sequential orchestration baseline, Phase 8 conversation integration and Phase 9 multi-agent expansion.
- Updated README, roadmap, documentation index, AI orchestration and Phase 7 execution records.

### Added (Phase 7 - Supervisor & Orchestrator)
- Bounded orchestration layer in `core/orchestration/`: typed, versioned contracts (Goal, Plan, TaskNode, Dependency, Assignment, Handoff, Evidence, AggregateResult) with explicit state transition tables, and a deterministic graph validator that rejects cycles, invalid or missing task references, unknown agent versions, invalid state transitions, and malformed planning output before any plan is persisted or scheduled.
- Deterministic sequential scheduler with persisted scheduling decisions, dependency-gated starts, duplicate-execution prevention, plan wall-clock and retry budgets, explicit failure/cancellation propagation, and restart-safe `reconcile` recovery.
- Explainable, least-privilege capability-based assignment over registered agents only; tool evidence through the ToolRegistry catalog, model evidence through the InterfaceManager, unknown capabilities stay unknown, and scope expansion beyond the parent goal is denied.
- Versioned `orchestration.handoff/1` handoff envelopes with size validation and bounded degradation, and deterministic result aggregation that surfaces conflicts and missing evidence.
- The `supervisor` agent 1.0.0 (zero tool calls, zero model tokens, deterministic behavior) hosted by the Phase 6 Agent Runtime, plus the trusted `OrchestrationService` composition root and idempotent bootstrap registration.
- WP-7.4 planning service: deterministic template plans and bounded, schema-validated LLM proposals (`orchestration.proposal/1`) requested only through the InterfaceManager, with nested plan decomposition rejected and revisions bounded.
- Loopback-protected orchestration API (`/api/orchestration/goals`, `/api/orchestration/plans` with execute/cancel/reconcile, and read-only plan views) and a minimal orchestration panel in the agents UI tab.
- SQLite schema migration `0006_orchestration` adding the orchestration goal, plan, node, dependency, assignment, handoff, and event tables; plans and nodes carry optimistic-concurrency versions, and assignment/handoff/event stores are append-only.
- WP-7.6 regression suite `tests/test_orchestration_supervisor.py` covering planning, scheduling, assignment denial paths, failure injection with bounded retries, cancellation, wall-clock budgets, and restart recovery without duplicated side effects.

### Added
- Bounded, application-owned Agent Runtime (Phase 6): versioned and validated agent definitions, a trusted application-side registry, persistent tasks/runs with checkpoints and optimistic concurrency, deterministic lifecycle transitions, restart recovery, budget-bounded execution (iterations, wall-clock deadline, tool calls, input/output bytes, model tokens), and truthful structured outcomes.
- Permission-checked scoped context assembly and least-privilege per-run capability grants; model calls go through the InterfaceManager only with a model route allowlist and explicit task-level transmission authorization, and tool calls go through ToolRuntime and the PermissionManager only.
- One builtin low-risk agent (`knowledge-analyzer`) that analyzes one explicitly bound knowledge scope read-only through the `knowledge_search` tool; no autonomous publishing, deletion, credential access, or external transmission.
- Loopback-protected agent lifecycle API (`/api/agents`, `/api/agents/runs`) with explicit pause/resume/cancel and approval handoff, plus a minimal run-status UI view.
- SQLite schema migration `0005_agent_runtime` adding the agent definition, task, run, checkpoint, and run-event tables.
- WP-6.7 regression suites covering contracts, registry, lifecycle and restart recovery, bounded execution budgets, permission denial paths, and per-run grant isolation.

### Fixed (CI remediation)
- The `knowledge_search` tool now declares a bounded output schema that matches the actual handler response (`count`, `truncated`, `results`); malformed outputs are rejected and the `truncated` flag reports the truth.
- Agent lifecycle transitions enforce caller-provided expected versions; stale snapshots are rejected with the domain concurrency error, and repeated starts fail as invalid transitions before the executor claim is taken.
- Agent definition lookups read through persistence, so a definition disabled or re-enabled outside a registry instance is never shadowed by a stale cache.
- The execution controller fails closed: unexpected context-assembly, capability, or tool-runtime errors fail the run with a redacted message, release the executor claim, and never expose sensitive context.
- API regression coverage for the loopback-protected agent endpoints: non-loopback and cross-origin denial, missing resources, invalid transitions, run and event serialization, approval-handoff rejection, and fail-closed execution without a trusted behavior.

### Added
- Start a fresh empty chat session on every app launch while keeping previous sessions available in the sidebar.
- Versioned settings migration that defaults new and legacy installations to OpenRouter with `openrouter/free`, while preserving later user provider selections.
- Google AI Studio/Gemini provider using the Interactions API with streaming and live model discovery.
- Cloudflare Workers AI, Groq, and Cohere provider adapters with streaming and live model discovery.
- Provider/model capability metadata for task suitability, context windows, tool calling, streaming, and free-tier quota semantics.
- Provider settings panels and secret-safe API-key/token storage for Cloudflare, Groq, and Cohere.
- Versioned settings migration that retires Hugging Face and migrates an active Hugging Face selection to OpenRouter.

### Added
- Collapsible right-hand conversation sidebar with persistent expanded/collapsed preference.
- Local profile settings with username, display name, email, and SQLite-persisted avatar images.
- Avatar upload validation (PNG/JPEG/WebP, 2 MB upload limit, 4096×4096 input limit) and 256×256 WebP normalization.
- Appearance settings with persistent dark/light theme selection and dedicated general/support sections.
- Frontend JavaScript syntax validation in CI.

### Security and scope
- Password management remains unavailable until a real authentication and account-session system is implemented.

### Fixed
- Removed the accidental abstract-method decorator from the concrete OpenRouter streaming implementation.
- Normalize OpenRouter base URLs to https://openrouter.ai/api/v1 and expose useful HTTP error response bodies.
- Create the SQLite data directory before initializing the database.
- Buffer incomplete Server-Sent Events in the browser instead of assuming network chunks align with event boundaries.

### Added
- Dynamic provider registry and API discovery endpoints.
- Provider-specific model selection in the UI.
- Live Ollama model discovery from /api/tags.
- OpenRouter free-model discovery and the openrouter/free automatic free-model router.
- Configuration migration from the legacy top-level model map.
- Secret redaction in settings API responses and preservation of stored secrets when blank fields are submitted.
- Unit tests and GitHub Actions CI workflow.

### Changed
- Updated README, architecture, security, and contribution documentation to reflect implemented functionality and identify planned features.
- Wired the Phase 6 agent bootstrap to the local-owner grant administration policy so trusted per-run capability grants can be issued while all other grant administration stays default-deny.
