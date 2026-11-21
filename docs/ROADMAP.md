# Product and Engineering Roadmap

**Status:** Target roadmap; implementation status is called out separately.  
**Last reviewed:** 2026-11-21

This roadmap describes the intended evolution of the Local AI Assistant. It must not be read as a claim that every listed capability already exists.

## Product direction

Build a local-first, provider-agnostic AI workspace with durable conversations, controlled access to local knowledge, replaceable online and offline execution paths, permissioned tools/connectors, and an auditable knowledge lifecycle.

The application itself, its database, and its managed local files are the primary data foundation. External services such as Discord and NotebookLM are optional connectors, not the system of record.

## Current implementation baseline

The repository currently contains a FastAPI application, a lightweight Alpine.js browser UI, SQLAlchemy-backed SQLite persistence, provider adapters, settings/configuration handling, chat streaming, and tests.

Provider integrations present in the current codebase include Ollama, OpenRouter, Google AI Studio/Gemini, Cloudflare Workers AI, Groq, and Cohere. The current chat experience still uses explicit provider/model selection. Capability metadata exists as groundwork; it does not mean the full Interface Manager, automatic task routing, or AI Supervisor is complete.

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

### Phase 1 — Persistence and repository foundation

**Goal:** Establish durable, replaceable data access without overbuilding the schema.

- Keep SQLite as the local database target.
- Design PostgreSQL compatibility for hosted/online deployment.
- Introduce versioned migrations and a repository/data-access boundary.
- Keep original files in independent file storage.
- Define stable identifiers, timestamps, ownership, and provenance conventions.
- Add SQLite FTS5 as the initial lexical search option.
- Keep vector indexing behind a replaceable adapter.

**Exit criteria:** Schema migrations are repeatable and tested; modules do not issue uncontrolled cross-domain SQL; file storage is independent of database storage.

### Phase 2 — Permission and credential foundations

**Goal:** Enforce access control in application code before introducing autonomous tools or ingestion.

- Define permission subjects, resources, scopes, operations, grants, expiry, revocation, and audit events.
- Centralize credential access and redaction.
- Keep secrets out of browser responses, logs, prompts, and ordinary backups.
- Require permission checks for connector, file, conversation, memory, and tool access.
- Define explicit user approval for sensitive write operations.

**Exit criteria:** Unauthorized access is denied by default and covered by tests; permission decisions are auditable.

### Phase 3 — Interface Manager and provider/model control plane

**Goal:** Turn current provider adapters into a coherent internal service.

- Maintain provider and model registries.
- Normalize provider adapter contracts and errors.
- Track model capabilities, context limits, modalities, tool support, streaming, and operational constraints.
- Manage credentials, connection state, health, timeout, retry, quota visibility, and fallback eligibility.
- Separate catalog refresh/update from request-time model selection.
- Provide internal APIs for other modules.

**Exit criteria:** Other modules can discover and invoke models without importing provider-specific SDKs or depending on vendor response formats.

### Phase 4 — Model and Provider Updater

**Goal:** Detect catalog and provider changes without silently changing user choices.

- Periodically check supported provider catalogs and relevant metadata.
- Compare new results with the stored catalog.
- Report added, changed, deprecated, unavailable, or removed models.
- Make updates visible and explain their impact.
- Do not replace a user's selected model without an explicit policy/confirmation.
- Treat pricing and free-tier eligibility as time-sensitive metadata, not permanent guarantees.

**Exit criteria:** Catalog refresh is observable, repeatable, and safe; unknown quota values remain unknown.

### Phase 5 — Prompt Manager and Conversation Processing

**Goal:** Build one conversation-processing module with two execution engines.

- Version and categorize prompts.
- Introduce request analysis, task planning, execution routing, context management, and conversation recording.
- Provide an Online Execution Engine using Interface Manager.
- Provide an Offline Execution Engine using local models and permitted local knowledge.
- Use deterministic/rule-based dispatch for basic routing, policy enforcement, and fallback.
- Keep complex LLM-based planning optional through an AI Supervisor.
- Preserve conversation and task provenance.

**Exit criteria:** Online and offline execution share the same conversation lifecycle and validation boundary; loss of a cloud provider does not disable eligible local workflows.

### Phase 6 — Response validation and safe tool execution

**Goal:** Ensure model output is checked and tool calls are mediated.

- Add a Response Validator & Composer independent from provider adapters.
- Validate structure, completeness, policy, references, and execution outcomes.
- Introduce a permissioned tool registry and isolated Tool Runtime.
- Treat model tool calls as proposals, not authorization.
- Log tool activity, arguments, results, and failures with sensitive-value redaction.

**Exit criteria:** No tool executes without an application-side permission decision; unvalidated model output is not silently promoted to trusted knowledge.

### Phase 7 — Knowledge Access and managed data

**Goal:** Expose controlled retrieval over application-owned data.

- Add a Knowledge Access Layer with permission-aware search and retrieval.
- Keep source files, extracted text, chunks, indexes, and approved knowledge distinct.
- Add metadata, versioning, hashing, and source locators.
- Start with lexical search; add vector retrieval only behind a replaceable adapter.
- Preserve provenance for every derived record.

**Exit criteria:** Retrieval respects source permissions and can return traceable references to original material.

### Phase 8 — Document ingestion and AI Librarian

**Goal:** Provide user-controlled analysis and curation of project knowledge.

- Add document extraction and incremental change detection.
- Add the Librarian workspace, analysis, classification, cross-reference, conflict detection, and report generation.
- Require source ingestion permission before reading/extracting a source.
- Validate reports and source coverage.
- Require user review and explicit approval before publishing to Approved Knowledge.
- Keep training-dataset preparation separate from RAG/knowledge retrieval.

**Exit criteria:** No source is ingested without a grant; no report is published as approved knowledge without user approval and provenance.

### Phase 9 — Connectors and Discord synchronization

**Goal:** Add optional integrations without making them authoritative dependencies.

- Define connector contracts and scoped credentials.
- Add Discord synchronization as an optional adapter for selected project status/context.
- Support explicit sync direction, scope, conflict handling, and audit logs.
- Consider Notebook integrations only when a supported, maintainable integration path exists.
- Never make an external service the only copy of project knowledge.

**Exit criteria:** Disconnecting a connector does not make local project data unavailable; synchronization is scoped and traceable.

### Phase 10 — Backup, maintenance, and hosted deployment

**Goal:** Protect user data and support an optional online deployment.

- Add consistent snapshots of all persistent application data.
- Back up original files and database state with a manifest.
- Encrypt sensitive backup material and define recovery procedures.
- Restrict maintenance cleanup to explicitly designated cache/temporary data.
- Add authentication, authorization, secure sessions, HTTPS, rate limits, and operational monitoring before public multi-user exposure.
- Use PostgreSQL for hosted deployment while retaining SQLite for local use.

**Exit criteria:** Restore is tested; secrets are protected; public deployment has authentication and security controls.

### Phase 11 — Quality and release readiness

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
