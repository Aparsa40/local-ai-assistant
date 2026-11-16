# System Architecture

## Overview

The application is designed around a decoupled, layered architecture to ensure that UI, routing logic, storage, and LLM inference backends can evolve independently.

```text
[ Browser UI (Alpine.js + Tailwind) ]
                 │  (HTTP POST + Server-Sent Events Stream)
                 ▼
[ FastAPI Backend (main.py) ]
                 │
                 ├──► [ ConfigManager ] ──► config/settings.json
                 ├──► [ Database (SQLite) ] ──► data/assistant.db
                 │
                 ▼
[ Model Orchestrator (core/orchestrator.py) ]
                 │
        ┌────────┴────────┐
        ▼                 ▼
[ OllamaProvider ] [ OpenRouterProvider ]
 (Local Inference)   (Cloud Inference)
```

## Core Components

1. **API Layer (`main.py`):** Exposes REST endpoints for session management and configuration, plus an async streaming endpoint (`/api/chat`) using `StreamingResponse`.
2. **Orchestrator (`core/orchestrator.py`):** Evaluates incoming prompts and routing modes (`auto`, `general`, `coder`, `reasoning`) to dispatch requests to the designated model.
3. **Provider Abstraction (`core/providers/`):** Implements `BaseLLMProvider`, enforcing a consistent `generate_stream()` async generator across all backends.
4. **Persistence (`core/database.py`):** Manages relational tables (`sessions` and `messages`) using Python's built-in `sqlite3` module with zero external ORM overhead.
