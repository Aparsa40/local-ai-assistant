# System Architecture

**Status:** Accepted target architecture plus current implementation notes  
**Last reviewed:** 2026-11-25

## 1. Architectural goals

The system is a local-first, provider-agnostic AI workspace. It must support local and cloud inference through replaceable adapters, preserve user-controlled data locally, and enforce permissions independently of model behavior.

The architecture distinguishes:
- **Current implementation:** code that exists in the repository today.
- **Accepted target design:** responsibilities and boundaries agreed for future implementation.
- **Planned capability:** work not yet implemented.

## 2. Current implementation snapshot

The current repository contains:
- FastAPI backend in `main.py`.
- Alpine.js browser UI in `static/`.
- Provider contracts and adapters in `core/providers/`.
- Configuration handling in `core/config_manager.py`.
- SQLAlchemy/SQLite persistence in `core/database.py`, managed through `core/storage/` and domain repositories in `core/repositories/`.
- Conversation/Profile Services, scoped MemoryService, bounded ContextManager, and Knowledge Storage in `core/conversations/`, `core/profiles/`, `core/memory/`, `core/context/`, and `core/knowledge/`.
- A default-deny PermissionManager with exact-scope grants, local-owner grant administration, action-bound approvals, redacted audit, and a bounded Tool Registry/Runtime in `core/permissions/` and `core/tools/`.
- A bounded Agent Runtime in `core/agents/`: versioned agent definitions, a trusted registry, deterministic lifecycle with optimistic concurrency and checkpoint/restart recovery, budget-bounded execution through ToolRuntime and PermissionManager, one builtin read-only knowledge-analysis agent, and loopback-only lifecycle APIs.
- A fixed local single-user policy for loopback and same-origin API requests; cross-origin browser calls and non-loopback clients are rejected. This is not authentication or hosted multi-user security.
- A current chat orchestrator in `core/orchestrator.py`.
- A provider-neutral Interface Manager service in `core/interface_manager.py`, used by provider APIs and chat streaming.
- An initial Local Model Runtime control plane in `core/runtime/`, with an Ollama lifecycle adapter, persistence, and explicit runtime API operations, including a combined read-only health/inventory snapshot.
- Provider and chat tests in `tests/`.

Current provider integrations include Ollama, OpenRouter, Google AI Studio/Gemini, Cloudflare Workers AI, Groq, and Cohere. The current user-facing flow still selects a provider and model explicitly. Interface Manager now provides a first service boundary for provider listing, local operator catalogs, capability access, bounded model discovery, catalog-reachability diagnostics, quota visibility, and chat streaming. The connection diagnostic probes model-catalog access only; it is not an end-to-end inference health check. A persistent Model Manager, scheduled Updater, full normalized request/response contract, and automatic routing are not implemented.

Operator-level catalog metadata is maintained locally and separated from exact live model discovery. OpenRouter key usage and observed Groq/Cohere response-header telemetry are exposed where supported; unknown balances remain unknown.

Phase 4 Knowledge Storage uses SQLite FTS5 across ordered schema revisions, and Phase 5 integrates exact-scope Knowledge permissions and action-bound approval for destructive local API operations. Phase 6 adds migration `0005_agent_runtime` with agent definition, task, run, checkpoint, and run-event tables, and registers one production read-only `knowledge_search` tool handler that a bounded execution loop invokes only through ToolRuntime and PermissionManager. No other production tool handlers are registered.

The current credential file is local and ignored by Git, but credentials are not yet protected by a dedicated encrypted credential vault. The application does not implement user authentication. The loopback-only `local-api` principal is a local single-user boundary, not identity verification. Do not expose the current application through a LAN, reverse proxy, or public network.

## 3. Target high-level architecture

```text
                         User / UI
                            |
                     Application API
                            |
                Conversation Processing
                 /                    \
        Request Analyzer           Context & Memory
                 |                       |
       Direct Response or Agent Task    |
                 |                       |
             Agent Runtime <-------------+
       Agent Registry / Lifecycle / State
                 |
       Supervisor & Specialized Agents
                 |
       Online / Offline Execution Strategy
                 |
          Interface Manager
        /       |          \
   Provider  Model/Capability  Connection /
   Registry    Catalog       Credential Services
        |
   Provider Adapters (cloud and local)

  Agent Runtime / Conversation Processing
                    |
        Response Validator & Composer
                    |
                Final Response
                    |
                     UI

  Tool & Permission Manager ---- Tool Runtime ---- Tools
              |
        Permission Registry

  Knowledge Access Layer ---- Repositories ---- SQLite / PostgreSQL
              |                       |
       Approved Knowledge        File Storage

  AI Librarian ---- Source Scanner / Extractor / Analyzer / Report Validator
       |                         |
  Librarian Workspace      Review & Approval
                                  |
                           Approved Knowledge

  Backup & Maintenance ---- Snapshot APIs / Cache Policies
```

This is a logical architecture. It does not require a separate process or database for every box. Phase 7 Supervisor/Orchestrator is implemented and merged via PR #21. Phase 8 Conversation Processing is implemented on branch `feat/phase-8-conversation-agent` as `core/conversation_agent/`; Phase 9 broader multi-agent orchestration remains planned work.

## 4. Core module responsibilities

### Interface Manager

The provider/model control plane. It owns provider registration, model catalog access, connection and credential integration, health/quota metadata, adapter invocation, and normalized provider results.

It exposes operator-level catalog metadata independently from optional live model discovery. Provider-level task tags are hints, not guarantees for every model. It does not decide whether a response is factually correct and does not own task planning.

### Local Model Runtime (initial foundation implemented)

Owns local inference-engine lifecycle operations through a provider-neutral Runtime Manager and Runtime Adapter contract. The first adapter controls Ollama process readiness and model installed/loaded state. Runtime lifecycle persistence is separate from provider catalog metadata and inference-success status. Runtime inspection is read-only; model load/unload are explicit operations. See [LOCAL_MODEL_RUNTIME.md](LOCAL_MODEL_RUNTIME.md).

The software foundation and CI acceptance are complete. Windows smoke validation verified runtime connectivity, inventory, inspection, and process-ownership safety. Live Qwen loading could not be verified on the observed 4 GB RAM machine while Chrome and VS Code were active; the mechanical HDD is not a practical substitute for RAM because sustained paging can make the system unresponsive. This is recorded as an environment-constrained validation gap, not a demonstrated implementation defect. Successful live load/unload on adequately provisioned hardware remains unverified. The current increment does not provide automatic model downloads, automatic eviction, GPU telemetry guarantees, or multi-engine support.

### Agent Runtime (implemented in Phase 6 for one bounded agent)

Hosts goal-oriented agents and manages their task lifecycle, state, bounded execution loops, handoffs, and completion evaluation. The Supervisor is a specialized agent hosted by this runtime, not the runtime itself. See [AGENT_RUNTIME.md](AGENT_RUNTIME.md).

Phase 6 implements versioned and validated agent definitions, a trusted application-side registry, deterministic lifecycle transitions with optimistic concurrency and restart recovery, checkpoint/resume support, budget-bounded execution through ToolRuntime and PermissionManager, one builtin read-only knowledge-analysis agent, and loopback-only lifecycle APIs and UI. The Phase 7 Supervisor/Orchestrator is implemented and merged via PR #21. Conversation Agent is Phase 8 planned work; broader multi-agent orchestration is Phase 9 planned work.

### Model & Provider Updater

Refreshes provider and model metadata on a schedule or on user request. It detects catalog changes and reports them. It must not silently replace a user's selected model.

### Conversation Processing Module

Owns the user-facing conversation lifecycle: request intake, conversation history, authorized context assembly, task handoff, event recording, and delivery of the validated result. The current chat API persists the user turn through ConversationService and assembles bounded conversation history through ContextManager. Memory scopes are not implicitly attached; retrieval requires explicit scope input.

Implemented in Phase 8 (`core/conversation_agent/`): versioned contracts, a deterministic dispatcher (advisory model classification may only downgrade to needs-user-input), separate retrieval and destination/egress authorization, normalized online/offline strategies through the InterfaceManager, bounded delegation through the Phase 7 OrchestrationService composition root, a response validator/composer with valid/partial/rejected states, and an idempotent in-process operation registry feeding a versioned SSE protocol. It does not own the lifecycle of specialized agent runs and never calls provider SDKs or the application's own HTTP endpoints.

### Supervisor Agent

A specialized coordinating agent hosted by Agent Runtime. It plans complex work, decomposes tasks, selects eligible agent roles and model capabilities, coordinates handoffs, and evaluates combined results.

It is not a separate infrastructure manager and cannot grant permissions or execute tools directly. Deterministic runtime code handles lifecycle transitions, policy checks, iteration limits, and simple workflows without requiring an LLM. The Supervisor/Orchestrator baseline is implemented and merged via PR #21; see the Phase 7 execution plan for delivered scope and limitations.

### Response Validator & Composer

An independent quality and policy boundary. It checks output structure, completeness, references, tool outcomes, and applicable safety rules, then prepares the response for the UI. It is used for both online and offline results.

It must not be folded into a provider adapter. Phase 8 implements the first version of this boundary in `core/conversation_agent/validator.py` and `composer.py`: schema, reference-existence, delegated-task-coverage, and policy checks with valid/partial/rejected states, plus truthful limitation text and mandatory fallback disclosure.

### Tool & Permission Manager (Phase 5 implemented; first Phase 6 handler)

The current implementation includes typed authorization contracts, exact-scope persistent grants with expiry/revocation, default-deny PermissionManager decisions, separate default-deny grant administration with a local-owner administration policy, action-hash-bound one-time approvals, redacted append-only audit events, an explicit versioned Tool Registry, and an async bounded Tool Runtime. Conversation/Profile Services, ContextManager, provider/runtime/configuration API routes, and the MemoryService adapter use centralized permission checks. The current local policy is loopback-only and single-user; it is not hosted authentication.

Phase 6 registers the first production tool handler, a read-only `knowledge_search` over one explicitly bound knowledge scope, and issues exact per-run grants for agents. Connector services, an encrypted credential vault, hosted multi-user identity, and further production tool handlers are not yet implemented. Models can request tool use, but only application code can register, authorize, and execute it.

### Knowledge Access Layer

Provides permission-aware retrieval over approved application knowledge and source data. It hides database and search-backend details from callers.

### AI Librarian

Analyzes only sources explicitly authorized for ingestion. It maintains a private working area, produces traceable reports, and publishes nothing to Approved Knowledge until the user approves the validated report.

### Data & File Management

Owns source-file metadata and managed file operations. Original files are not replaced by extracted text, summaries, embeddings, or reports.

### Backup & Maintenance

Backup reads consistent snapshots through owner-controlled APIs. Maintenance is limited to designated temporary/cache data and retention policies. Neither module becomes the owner of other modules' records.

## 5. Online and offline execution

Agent Runtime selects an execution strategy for agent tasks based on actual task requirements and available capabilities. Conversation Processing may use the same provider-neutral execution boundary for direct conversational requests.

- Online path: Agent Runtime / Conversation Processing -> Online Execution Strategy -> Interface Manager -> cloud provider adapter.
- Offline path: Agent Runtime / Conversation Processing -> Offline Execution Strategy -> Interface Manager -> local provider adapter (for example, Ollama).
- Provider availability, credentials, health, quota state, model capability, and task constraints influence routing.
- Internet connectivity alone is not a reason to choose the online path.
- If no LLM is available, deterministic search, retrieval, extraction, and fixed workflows may still run. The system must clearly state when a task requires language-model reasoning that is unavailable.

Both paths converge on Response Validator & Composer before the final answer is presented. The two execution strategies and Response Validator & Composer remain accepted target design; the Phase 6 Agent Runtime invokes models only through InterfaceManager behind an explicit route allowlist and task-level transmission authorization, so no private local context can reach a cloud provider implicitly.

## 6. Data and ownership boundaries

SQLite is the local database target. PostgreSQL is the hosted/online target. A repository/data-access layer separates domain logic from SQL dialects. File storage remains independent of the database.

Logical data domains may share one physical database. They are not separate databases merely because they belong to different modules.

A module accesses another domain through documented APIs/repositories and permission checks. Direct cross-module table mutation is prohibited.

## 7. AI Librarian data lifecycle

The Librarian uses three logical states in the knowledge system:

1. **Librarian Workspace:** extracted working material, metadata, analysis, and draft reports; private and not generally retrievable as approved knowledge.
2. **Review & Approval:** validated reports awaiting user review; still not approved knowledge.
3. **Approved Knowledge:** user-approved reports and reference material available to authorized modules through Knowledge Access.

These are logical states/scopes, not three mandatory physical databases. The Librarian does not own or modify original sources.

## 8. Security and trust boundaries

- Provider adapters are untrusted boundaries for external responses.
- Connector payloads and imported files are untrusted input.
- Model output is untrusted until validated.
- Permission decisions are made by application services, not by model prompts.
- Credentials must be redacted from logs, UI payloads, and model context.
- Cross-domain access must be scoped and auditable.
- User approval is required before Librarian publication.

## 9. Architectural constraints

See [PROJECT_PRINCIPLES.md](PROJECT_PRINCIPLES.md) for non-negotiable constraints. Module-specific contracts are defined in the remaining documents in this directory.

## 10. Implementation status discipline

A design diagram is not proof of implementation. Every feature in documentation, UI, or release notes must be labeled accurately as implemented, accepted design, or planned. Update this snapshot whenever runtime behavior changes.
