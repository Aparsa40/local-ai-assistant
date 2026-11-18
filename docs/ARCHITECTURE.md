# Architecture

## Runtime flow

```text
Browser UI
   │ REST + Server-Sent Events
   ▼
FastAPI (main.py)
   ├── ConfigManager ── config/settings.json
   ├── Provider discovery API
   ├── Session API ── SQLAlchemy ── SQLite (data/chat_history.db)
   └── Orchestrator
          │
          ▼
     Provider Registry
       ├── OllamaProvider
       └── OpenRouterProvider
```

## Provider contract

Every provider implements BaseLLMProvider:

- chat_stream(messages, model, temperature): async generator of text chunks.
- list_models(): async retrieval of model identifiers selectable in the UI.

Provider construction is delegated to core/providers/registry.py. Register a provider factory with register_provider(name, factory). The API returns registered provider IDs and calls the selected provider's list_models() method. The UI does not need a hard-coded provider list.

## Model selection

Choices are stored per provider:

- providers_config.ollama.model is an installed Ollama model tag.
- providers_config.openrouter.model is an OpenRouter model ID. It defaults to openrouter/free.

The old top-level models object is read during migration to preserve its general model as the initial Ollama selection.

## API endpoints

- GET /api/settings: public settings; secret values are redacted.
- POST /api/settings: partial settings update; blank secret fields preserve stored values.
- GET /api/providers: registered providers.
- GET /api/providers/{provider_id}/models: models discovered from that provider.
- POST /api/chat: streamed response using the active provider and selected model.
- /api/sessions: SQLite-backed chat sessions and messages.

## Provider behavior

### Ollama

- Model catalog: GET {base_url}/api/tags.
- Streaming chat: POST {base_url}/api/chat.
- Default URL: http://localhost:11434.

### OpenRouter

- Base URL is normalized to include /api/v1.
- Model catalog: GET /models; the UI list is filtered to zero-priced models and :free variants, with openrouter/free always offered.
- Streaming chat: POST /chat/completions.
- HTTP error response bodies are included in provider errors.

## Persistence

SQLAlchemy manages sessions and messages in SQLite at data/chat_history.db. The data directory is created before the engine initializes.

## Security boundaries

The settings API does not return stored API keys. Keys are still stored in the local ignored JSON settings file, so OS-level account protection is required. The app has no user authentication; keep it bound to localhost and do not expose it to untrusted networks.
