# Changelog

All notable changes are documented here. The project follows Semantic Versioning.

## Unreleased

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
