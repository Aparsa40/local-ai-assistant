# Product Roadmap

This roadmap describes the intended evolution of the Persian-first local and online AI assistant. It separates shipped foundations from planned capabilities so the UI does not imply functionality that is not implemented yet.

## Product direction

Build a reliable, privacy-conscious, multi-provider AI workspace that works offline-first with local models and can optionally use cloud models. Conversations, reusable knowledge, files, tools, and provider connections should be managed through one coherent interface.

## Current foundation

- FastAPI backend with a lightweight Alpine.js browser interface.
- Provider registry and adapters for Ollama (local), OpenRouter, Google AI Studio/Gemini, and Hugging Face Inference Providers.
- Streaming chat responses.
- SQLite persistence through SQLAlchemy for chat sessions, messages, and the local user profile.
- Session title editing and session deletion.
- Fresh chat session on every app launch while retaining prior chat history.
- Versioned settings migration with OpenRouter as the default for new/legacy installations.
- Basic profile, appearance, provider, and prompt settings.

## Phase 1 — Conversation lifecycle and reliability

**Goal:** Make chat history safe and dependable before adding more data types.

- Complete session create, select, rename, and delete workflows.
- Deleting a session must also delete all its messages in the same database transaction.
- Confirm destructive actions and prevent deleting the active session while a response is streaming.
- When the active session is deleted, select another existing session or create a fresh empty session.
- Add export/backup and restore before introducing bulk destructive operations.
- Add UI and API tests for session lifecycle and failure cases.

## Phase 2 — Knowledge and memory management

**Goal:** Turn the current “Documents & Memory” placeholder into a real, user-controlled knowledge workspace.

Planned data model (separate from chat history):

- knowledge_items: title, type, content/metadata, source, created/updated timestamps, and optional tags.
- documents: original filename, MIME type, size, storage location, processing status, and timestamps.
- document_chunks: extracted text chunks and their document references, ready for later retrieval indexing.
- Optional memory_entries: concise reusable facts or preferences with provenance and lifecycle controls.

Planned UI:

- List and search saved items; open, edit, and inspect each item.
- Delete one selected item.
- Select multiple items and delete them in one confirmed bulk operation.
- Clearly distinguish saved knowledge from chat sessions and temporary cache.
- Show storage usage and processing state where meaningful.

The first implementation should use SQLite metadata and safe local file storage. Vector search/embeddings should be a later, replaceable layer rather than a hard dependency of the initial CRUD workflow.

## Phase 3 — Safe cache and storage maintenance

**Goal:** Let users reclaim temporary storage without accidentally deleting valuable data.

- Define explicit cache locations and ownership before exposing a cleanup action.
- Add a “Clear application cache” action with a preview of what will be removed.
- Clear only regenerable temporary data (for example, stale extraction artifacts, temporary uploads, and explicitly designated cache files).
- Never delete chat sessions, messages, saved knowledge, original documents, provider settings, or profile data as part of cache cleanup.
- Use an allowlisted cache directory, path validation, and atomic cleanup; do not recursively delete arbitrary paths supplied by the browser.
- Report the cleanup result and any files that could not be removed.

The current application does not yet have a dedicated application-cache subsystem. Browser cache and persistent application data are not interchangeable with an application cache.

## Phase 4 — Document ingestion and retrieval

- Support TXT, Markdown, PDF, and DOCX ingestion with file type and size validation.
- Extract text in a background task and preserve the original document.
- Split extracted text into traceable chunks.
- Add retrieval-augmented generation (RAG) with citations back to source documents.
- Start with a replaceable local vector-store adapter; evaluate SQLite FTS as a lightweight lexical-search baseline.
- Provide document reprocessing and deletion that also removes derived chunks and indexes.

## Phase 5 — Provider and model ecosystem

**Initial provider integrations implemented:** Ollama, OpenRouter, Google AI Studio/Gemini (Interactions API), and Hugging Face Inference Providers. Provider-specific model IDs are discovered dynamically; Hugging Face model/provider options are limited to live entries marked free by the provider catalog.

Remaining work:
- Add provider health checks, connection diagnostics, timeout/retry policies, and clearer quota/error reporting.
- Add model capability metadata (context length, vision, tools, streaming, structured output) instead of assuming all models behave alike.
- Add per-conversation provider/model selection and optional routing policies.
- Move secrets to environment variables or a managed secret store for hosted deployments.
- Build the task-based architect/router that classifies each request and chooses the appropriate model/provider. This is a separate phase after provider reliability and capability metadata.

## Phase 6 — Tools, connectors, and agent workflows

- Introduce a permissioned tool registry with explicit user approval for sensitive actions.
- Add MCP connections and scoped filesystem access.
- Add GitHub, project files, and other connectors through isolated adapters.
- Show tool activity, inputs, outputs, and failures transparently in the conversation.
- Add confirmations, audit events, and least-privilege access for write operations.

## Phase 7 — Online deployment and multi-user security

**Goal:** Support remote access without compromising the local-first experience.

- Add authentication, session ownership, authorization checks, and secure password/session handling.
- Introduce user-scoped data ownership for sessions, messages, documents, and memory.
- Add HTTPS, secure cookies, CSRF protection where applicable, rate limiting, request-size limits, and security headers.
- Move secrets to environment variables or a managed secret store.
- Add database backup/restore, migrations, retention controls, and operational health checks.
- Evaluate PostgreSQL for hosted multi-user deployments; retain SQLite as the simple local/single-user default.
- Do not expose the current unauthenticated development server to public networks.

## Phase 8 — Quality, usability, and release readiness

- Add browser-level tests for critical chat and settings workflows.
- Add accessibility and responsive-layout checks, including Persian RTL and keyboard navigation.
- Add structured logging, diagnostics, and privacy-aware telemetry that is disabled or opt-in by default.
- Document installation, local-model setup, cloud-provider setup, backup, recovery, and security boundaries.
- Maintain CI gates, dependency updates, release notes, and versioned database migrations.

## Data ownership and deletion rules

| Data category | Stored in | Delete behavior |
| --- | --- | --- |
| Chat session | SQLite sessions table | Delete the session and its messages |
| Chat messages | SQLite messages table | Deleted with the parent session |
| Profile | SQLite user_profile table | Separate profile-management action |
| Saved memory / knowledge | Planned knowledge tables | Individual and bulk deletion |
| Original documents | Planned managed file storage | Explicit document deletion, including derived data |
| Temporary cache | Planned dedicated cache area | Clear cache without touching persistent records |
| Provider configuration | Local settings file today | Separate settings action; never part of cache cleanup |

## Database evolution principles

- Keep schema changes versioned and migrate existing databases safely.
- Use foreign keys and explicit cascade rules for dependent records.
- Add indexes for common owner, session, type, and timestamp lookups.
- Use transactions for destructive and bulk operations.
- Keep original documents separate from extracted text and derived indexes.
- Add backup/restore before enabling broad bulk deletion in the knowledge workspace.
