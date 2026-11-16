# Versioning Policy

This project follows **Semantic Versioning (SemVer)** (`MAJOR.MINOR.PATCH`):

- **MAJOR (`X.0.0`):** Incompatible API changes, major database schema migrations, or core architectural overhauls.
- **MINOR (`0.X.0`):** New backward-compatible features (e.g., adding a new LLM provider, RAG support, or GitHub tool integration).
- **PATCH (`0.0.X`):** Backward-compatible bug fixes, performance optimizations, and documentation updates.

## Pre-Release Milestones (`0.x.x`)
- `0.1.x`: Core chat engine, Ollama/OpenRouter providers, SQLite storage, offline UI.
- `0.2.x`: Document ingestion & RAG (Retrieval-Augmented Generation) via `nomic-embed-text`.
- `0.3.x`: External tool execution (GitHub connector, web search, local file tools).
- `1.0.0`: Production-ready release with full test coverage and automated migrations.
