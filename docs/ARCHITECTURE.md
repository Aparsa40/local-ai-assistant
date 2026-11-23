# System Architecture

**Status:** Accepted target architecture plus current implementation notes  
**Last reviewed:** 2026-11-21

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
- SQLAlchemy/SQLite persistence in `core/database.py`.
- A current chat orchestrator in `core/orchestrator.py`.
- A provider-neutral Interface Manager service in `core/interface_manager.py`, used by provider APIs and chat streaming.\n- An initial Local Model Runtime control plane in `core/runtime/`, with an Ollama lifecycle adapter, persistence, and explicit runtime API operations.
- Provider and chat tests in `tests/`.

Current provider integrations include Ollama, OpenRouter, Google AI Studio/Gemini, Cloudflare Workers AI, Groq, and Cohere. The current user-facing flow still selects a provider and model explicitly. Interface Manager now provides a first service boundary for provider listing, local operator catalogs, capability access, bounded model discovery, catalog-reachability diagnostics, quota visibility, and chat streaming. The connection diagnostic probes model-catalog access only; it is not an end-to-end inference health check. A persistent Model Manager, scheduled Updater, full normalized request/response contract, and automatic routing are not implemented.

Operator-level catalog metadata is maintained locally and separated from exact live model discovery. OpenRouter key usage and observed Groq/Cohere response-header telemetry are exposed where supported; unknown balances remain unknown.

The current credential file is local and ignored by Git, but credentials are not yet protected by a dedicated encrypted credential vault. The application does not yet implement user authentication. Do not expose the current development server to untrusted networks.

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

This is a logical architecture. It does not require a separate process or database for every box. Agent Runtime and its agents are accepted target design, not current shipped functionality.

This is a logical architecture. It does not require a separate process or database for every box.

## 4. Core module responsibilities

### Interface Manager

The provider/model control plane. It owns provider registration, model catalog access, connection and credential integration, health/quota metadata, adapter invocation, and normalized provider results.

It exposes operator-level catalog metadata independently from optional live model discovery. Provider-level task tags are hints, not guarantees for every model. It does not decide whether a response is factually correct and does not own task planning.

### Local Model Runtime (initial foundation implemented)\n\nOwns local inference-engine lifecycle operations through a provider-neutral Runtime Manager and Runtime Adapter contract. The first adapter controls Ollama process readiness and model installed/loaded state. Runtime lifecycle persistence is separate from provider catalog metadata and inference-success status. Runtime inspection is read-only; model load/unload are explicit operations. See [LOCAL_MODEL_RUNTIME.md](LOCAL_MODEL_RUNTIME.md).\n\nThe current increment does not provide automatic model downloads, automatic eviction, GPU telemetry guarantees, or multi-engine support.\n\n### Agent Runtime (accepted target; not implemented)

Hosts goal-oriented agents and manages their task lifecycle, state, bounded execution loops, handoffs, and completion evaluation. The Supervisor is a specialized agent hosted by this runtime, not the runtime itself. See [AGENT_RUNTIME.md](AGENT_RUNTIME.md).

### Model & Provider Updater

Refreshes provider and model metadata on a schedule or on user request. It detects catalog changes and reports them. It must not silently replace a user's selected model.

### Conversation Processing Module

Owns the user-facing conversation lifecycle: request intake, conversation history, authorized context assembly, task handoff, event recording, and delivery of the validated result.

It decides whether a request can be answered directly, handled by a deterministic workflow, or delegated to Agent Runtime. It does not own the lifecycle of specialized agent runs.

### Supervisor Agent

A specialized coordinating agent hosted by Agent Runtime. It plans complex work, decomposes tasks, selects eligible agent roles and model capabilities, coordinates handoffs, and evaluates combined results.

It is not a separate infrastructure manager and cannot grant permissions or execute tools directly. Deterministic runtime code handles lifecycle transitions, policy checks, iteration limits, and simple workflows without requiring an LLM.

### Response Validator & Composer

An independent quality and policy boundary. It checks output structure, completeness, references, tool outcomes, and applicable safety rules, then prepares the response for the UI. It is used for both online and offline results.

It must not be folded into a provider adapter.

### Tool & Permission Manager

Maintains tool permissions and mediates access. Models can request tool use, but only application code can authorize and execute it.

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

Both paths converge on Response Validator & Composer before the final answer is presented. Agent Runtime and the two execution strategies are accepted target design, not implemented functionality.

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
