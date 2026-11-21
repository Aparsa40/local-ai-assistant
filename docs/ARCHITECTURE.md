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
- Provider and chat tests in `tests/`.

Current provider integrations include Ollama, OpenRouter, Google AI Studio/Gemini, Cloudflare Workers AI, Groq, and Cohere. The current user-facing flow still selects a provider and model explicitly. The existing provider capability manifest is groundwork, not the complete target Interface Manager or automatic AI Supervisor.

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
            Task Planner ---------------+
                 |
          Execution Router
             /       \
            /         \
   Online Engine     Offline Engine
        |                 |
        +------+----------+
               |
        Interface Manager
        /       |        \
   Provider  Model    Connection /
   Registry  Catalog  Credential Services
        |
   Provider Adapters

  Conversation Processing
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
            |                      |
       Approved Knowledge     File Storage

  AI Librarian ---- Source Scanner / Extractor / Analyzer / Report Validator
       |                         |
  Librarian Workspace      Review & Approval
                                  |
                           Approved Knowledge

  Backup & Maintenance ---- Snapshot APIs / Cache Policies
```

This is a logical architecture. It does not require a separate process or database for every box.

## 4. Core module responsibilities

### Interface Manager

The provider/model control plane. It owns provider registration, model catalog access, connection and credential integration, health/quota metadata, adapter invocation, and normalized provider results.

It does not decide whether a response is factually correct and does not own task planning.

### Model & Provider Updater

Refreshes provider and model metadata on a schedule or on user request. It detects catalog changes and reports them. It must not silently replace a user's selected model.

### Conversation Processing Module

The single conversation lifecycle and execution coordinator. It contains request analysis, planning, routing, context/memory access, online and offline execution engines, and conversation recording.

The two engines are execution strategies within one module, not two independent products.

### AI Manager / Supervisor

Coordinates complex tasks, decomposition, model selection, tool planning, and multi-model work. It may use an LLM, but must not be a single point of failure.

A deterministic dispatcher must handle basic routing, policy checks, simple workflows, and fallback without requiring an LLM.

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

The Conversation Processing Module chooses an execution path based on actual task requirements and available capabilities.

- Online path: Conversation Processing -> Online Engine -> Interface Manager -> provider adapter.
- Offline path: Conversation Processing -> Offline Engine -> local model adapter and permitted local knowledge.
- Provider availability, credentials, health, quota state, model capability, and task constraints influence routing.
- Internet connectivity alone is not a reason to choose the online path.
- If no LLM is available, deterministic search, retrieval, extraction, and fixed workflows may still run. The system must clearly state when a task requires language-model reasoning that is unavailable.

Both paths converge on Response Validator & Composer before the final answer is presented.

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
