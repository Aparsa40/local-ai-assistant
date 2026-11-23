# Product and Engineering Roadmap

**Status:** Target roadmap; implementation status is called out separately.  
**Last reviewed:** 2026-11-21

This roadmap describes the intended evolution of the Local AI Assistant. It must not be read as a claim that every listed capability already exists.

## Product direction

Build a local-first, provider-agnostic AI workspace with durable conversations, controlled access to local knowledge, replaceable online and offline execution paths, permissioned tools/connectors, and an auditable knowledge lifecycle.

The application itself, its database, and its managed local files are the primary data foundation. External services such as Discord and NotebookLM are optional connectors, not the system of record.

## Current implementation baseline

The repository currently contains a FastAPI application, a lightweight Alpine.js browser UI, SQLAlchemy-backed SQLite persistence, provider adapters, settings/configuration handling, chat streaming, and tests.

Provider integrations present in the current codebase include Ollama, OpenRouter, Google AI Studio/Gemini, Cloudflare Workers AI, Groq, and Cohere. The current chat experience still uses explicit provider/model selection. A first Interface Manager service boundary now handles provider listing, capability access, bounded model discovery, catalog-reachability diagnostics, and chat streaming. The local operator catalog manifest and provider-neutral catalog/quota endpoints are implemented. Persistent model history, scheduled Updater, automatic routing, Agent Runtime, and Supervisor remain future work.

The current application also has important limitations: credentials are stored in the ignored local settings JSON file, authentication is not implemented, and the current application must not be exposed to untrusted networks. See README and ARCHITECTURE for the implementation snapshot.

## Target phases

Phases are dependency-oriented milestones. Their exact size and release boundaries may be adjusted after design review, but later phases must not bypass the foundations they depend on.

### Phase 0 — Architecture and documentation baseline

**Goal:** Establish a shared contract before delegating implementation.

- Maintain the project principles and target architecture.
- Define module responsibilities, data ownership, internal APIs, permission boundaries, and acceptance criteria.
- Separate implemented behavior from accepted design and planned work.
- Provide an AI contribution guide so delegated models do not invent requirements.
- Review existing code and tests before each implementation task.

**Exit criteria:** The architecture documents agree with one another; each planned module has a clear owner, inputs, outputs, dependencies, and explicit non-goals.

### Phase 1 — Interface Manager and provider/model control plane

**Goal:** Turn existing provider adapters into a provider-neutral service before adding autonomous workflows.

- Keep provider adapters isolated behind the registry.
- Introduce the Interface Manager service boundary.
- Route provider listing, capability access, model discovery, and inference streaming through it.
- Add bounded catalog diagnostics and safe provider-neutral errors.
- Maintain operator-level catalogs independently from exact model IDs, including discovery scope, account permissions, task hints, and quota visibility.
- Keep live model discovery optional and explicit; never infer model availability or remaining quota from a provider-level profile.
- Expose live quota only when an authoritative endpoint or observed response headers provide it.
- Preserve exact model IDs and existing user-selected provider/model behavior.
- Keep Ollama/local inference behind the same provider-neutral contract as cloud providers.

**Current implementation:** The first service boundary, local operator catalogs, explicit live model discovery, catalog probe, normalized quota-visibility endpoint, and chat-stream delegation are implemented on the feature branch. OpenRouter key usage can be queried live; Groq/Cohere telemetry depends on observed response headers. Persistent model records, scheduled Updater, full health monitoring, normalized inference envelopes, retry/fallback policies, and an encrypted credential vault remain incomplete.

**Exit criteria:** Internal modules can discover and invoke providers through Interface Manager without importing provider-specific adapters. Catalog diagnostics are bounded and accurately labeled.
\n### Phase 2A — Local Model Runtime foundation\n\n**Goal:** Add a provider-neutral control plane for local inference runtimes before autonomous conversation or agent execution.\n\n- Define the Runtime Adapter and Runtime Manager contracts.\n- Reuse the existing safe Ollama process controller and register Ollama as the first runtime adapter.\n- Distinguish installed, loaded, and inference-available model states.\n- Support explicit load/unload operations, bounded timeouts, process ownership, and conservative resource admission.\n- Persist runtime lifecycle state and events separately from provider catalog and inference status.\n- Keep runtime inspection read-only and lifecycle mutations on explicit POST endpoints.\n\n**Current implementation:** The initial Runtime Manager, Ollama adapter, SQLite lifecycle state/event tables, and runtime status/model/load/unload API are implemented on `feat/local-model-runtime-foundation`; CI and Windows Ollama smoke validation are pending. Hardware telemetry, automatic eviction, model downloads, and other local engines remain deferred.\n\n**Exit criteria:** Runtime Manager is provider-agnostic; Ollama lifecycle operations are bounded and tested; only application-owned processes can be stopped; installed and loaded state are distinct; all existing tests remain green.\n
### Phase 2 — Persistence and repository foundation

**Goal:** Establish durable, replaceable data access before storing catalog history, agent runs, and knowledge artifacts.

- Keep SQLite as the local database target.
- Design PostgreSQL compatibility for hosted/online deployment.
- Introduce versioned migrations and a repository/data-access boundary.
- Keep original files in independent file storage.
- Define stable identifiers, timestamps, ownership, and provenance conventions.
- Add SQLite FTS5 as the initial lexical search option.
- Keep vector indexing behind a replaceable adapter.
- Avoid speculative tables until an owning workflow is ready.

**Exit criteria:** Migrations are repeatable and tested; modules do not issue uncontrolled cross-domain SQL; file storage is independent of database storage.

### Phase 3 — Model and Provider Updater

**Goal:** Detect provider/model catalog changes without silently changing user choices.

- Refresh supported provider catalogs on explicit request and, later, on a configurable schedule.
- Compare new catalog results with last-known state.
- Report added, changed, deprecated, unavailable, or removed models.
- Track catalog source, retrieval time, and capability evidence.
- Make updates visible and explain their impact.
- Never replace a user's selected model without explicit policy/confirmation.
- Treat pricing and free-tier eligibility as time-sensitive metadata.

**Exit criteria:** Catalog refresh is observable, repeatable, and safe; unknown quota/capability values remain unknown.

### Phase 4 — Permission and credential foundations

**Goal:** Enforce access control before autonomous tools, connectors, or ingestion are introduced.

- Define permission subjects, resources, scopes, operations, grants, expiry, revocation, and audit events.
- Centralize credential access and redaction; plan encrypted local secret storage.
- Keep secrets out of browser responses, logs, prompts, and ordinary backups.
- Require permission checks for connector, file, conversation, memory, and tool access.
- Define explicit user approval for sensitive write operations.
- Keep model-generated tool calls as proposals, never as authorization.

**Exit criteria:** Unauthorized access is denied by default and covered by tests; permission decisions are auditable.

### Phase 5 — Conversation Processing and online/offline execution

**Goal:** Build one conversation lifecycle that can use either cloud or local inference.

- Introduce request analysis, context assembly, task planning, execution routing, and conversation recording.
- Provide an Online Execution Strategy using Interface Manager.
- Provide an Offline Execution Strategy using local provider adapters and permitted local knowledge.
- Use deterministic dispatch for basic routing, fixed workflows, policy checks, and fallback.
- Preserve task checkpoints and re-check model capabilities when switching engines.
- Never send private local data to a cloud provider as an implicit fallback.
- Keep complex LLM-based planning optional.

**Exit criteria:** Online and offline execution share the same lifecycle and validation boundary; eligible local workflows remain usable without internet.

### Phase 6 — Response validation and safe tool execution

**Goal:** Validate model outputs and mediate every tool action.

- Add Response Validator & Composer independently from provider adapters.
- Validate structure, completeness, policy, references, and execution outcomes.
- Introduce a permissioned tool registry and isolated Tool Runtime.
- Treat model tool calls as proposals, not authorization.
- Record tool activity, arguments, results, and failures with sensitive-value redaction.
- Require explicit approval for sensitive or externally visible actions.

**Exit criteria:** No tool executes without an application-side permission decision; unvalidated output is not promoted to trusted knowledge.

### Phase 7 — Agent Runtime and the first single-agent workflow

**Goal:** Execute one bounded goal-oriented workflow reliably before introducing multiple agents.

- Define versioned Agent, Task, Run, State, Input, Output, and Completion Criteria contracts.
- Add Agent Registry, Lifecycle Manager, Task Manager, State Manager, and bounded Execution Controller.
- Support pause, resume, cancellation, iteration limits, and auditable outcomes.
- Host one specialized agent using online or offline inference through the same Interface Manager boundary.
- Enforce least-privilege context and permissioned tools.
- Start with a workflow that has no autonomous external side effects.

**Exit criteria:** One agent can complete a bounded task, preserve state, stop safely, and pass deterministic lifecycle and permission tests.

### Phase 8 — Supervisor and Multi-Agent orchestration

**Goal:** Coordinate multiple specialized agents through explicit task contracts.

- Implement Supervisor as a specialized agent hosted by Agent Runtime.
- Add agent selection, task decomposition, dependencies, structured handoffs, and result aggregation.
- Support different models per agent without making model count the definition of Multi-Agent.
- Preserve provenance and expose disagreements or incomplete results.
- Prevent agents from inheriting or expanding permissions implicitly.
- Add concurrency only after sequential handoffs and cancellation are reliable.

**Exit criteria:** Multiple agents can collaborate on a bounded task with traceable handoffs, enforced permissions, and validated final output.

### Phase 9 — Knowledge Access and managed data

**Goal:** Expose controlled retrieval over application-owned data.

- Add a Knowledge Access Layer with permission-aware search and retrieval.
- Keep source files, extracted text, chunks, indexes, and approved knowledge distinct.
- Add metadata, versioning, hashing, and source locators.
- Start with lexical search; add vector retrieval only behind a replaceable adapter.
- Preserve provenance for every derived record.

**Exit criteria:** Retrieval respects source permissions and can return traceable references to original material.

### Phase 10 — Document ingestion and AI Librarian

**Goal:** Provide user-controlled analysis and curation of project knowledge.

- Add document extraction and incremental change detection.
- Add the Librarian workspace, analysis, classification, cross-reference, conflict detection, and report generation.
- Require source ingestion permission before reading/extracting a source.
- Validate reports and source coverage.
- Require user review and explicit approval before publishing to Approved Knowledge.
- Keep training-dataset preparation separate from RAG/knowledge retrieval.

**Exit criteria:** No source is ingested without a grant; no report is published as approved knowledge without user approval and provenance.

### Phase 11 — Connectors and Discord synchronization

**Goal:** Add optional integrations without making them authoritative dependencies.

- Define connector contracts and scoped credentials.
- Add Discord synchronization as an optional adapter for selected project status/context.
- Support explicit sync direction, scope, conflict handling, and audit logs.
- Consider Notebook integrations only when a supported, maintainable integration path exists.
- Never make an external service the only copy of project knowledge.

**Exit criteria:** Disconnecting a connector does not make local project data unavailable; synchronization is scoped and traceable.

### Phase 12 — Backup, maintenance, and hosted deployment

**Goal:** Protect user data and support an optional online deployment.

- Add consistent snapshots of all persistent application data.
- Back up original files and database state with a manifest.
- Encrypt sensitive backup material and define recovery procedures.
- Restrict maintenance cleanup to explicitly designated cache/temporary data.
- Add authentication, authorization, secure sessions, HTTPS, rate limits, and operational monitoring before public multi-user exposure.
- Use PostgreSQL for hosted deployment while retaining SQLite for local use.

**Exit criteria:** Restore is tested; secrets are protected; public deployment has authentication and security controls.

### Phase 13 — Quality and release readiness

- Add integration and browser-level tests for critical workflows.
- Test Persian RTL, keyboard navigation, accessibility, and responsive layouts.
- Add privacy-aware diagnostics and structured logging.
- Keep release notes, migrations, and documentation synchronized with code.
- Define measurable acceptance criteria for each release.

## Cross-phase rules

- Never mark planned functionality as implemented.
- Do not introduce a module without documenting its boundary and data ownership.
- Do not add large sets of speculative database tables before their owning workflows exist.
- Every destructive operation requires an explicit scope and safe transaction/rollback strategy.
- Every AI-derived artifact must retain provenance and a validation state.
- External connectors remain optional.
- A phase is not complete merely because code exists; tests, documentation, and acceptance criteria must also pass.
