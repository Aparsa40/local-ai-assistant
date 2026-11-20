# Changelog

All notable changes are documented here. The project follows Semantic Versioning.

## Unreleased

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
