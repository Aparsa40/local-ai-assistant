# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org).

## - 2026-11-17

### Added
- Initial modular architecture using FastAPI and async HTTP streaming (`httpx`).
- Pluggable LLM provider layer supporting **Ollama** (local) and **OpenRouter** (cloud).
- Task-based model orchestrator (`general`, `coder`, `reasoning`, `auto` modes).
- Persistent SQLite database (`core/database.py`) for chat sessions and message history.
- Self-contained, offline-first web interface using local `TailwindCSS`, `Alpine.js`, and `Marked.js`.
- Configuration management system with `settings.example.json` template.

### Changed
- Optimized Ollama payload parameters (`num_ctx: 1024`, `num_thread: 2`) to support low-RAM environments (4GB RAM).
