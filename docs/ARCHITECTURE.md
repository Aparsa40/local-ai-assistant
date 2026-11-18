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
       ├── OpenRouterProvider
       ├── GoogleAIStudioProvider
       └── HuggingFaceProvider
```

## Provider contract

Every provider implements BaseLLMProvider:

- `chat_stream(messages, model, temperature)`: async generator of text chunks.
- `list_models()`: async retrieval of exact model identifiers selectable in the UI.

Provider construction is delegated to `core/providers/registry.py`. The API returns registered provider IDs and calls the selected provider's `list_models()` method. The UI discovers the registry dynamically.

## Model selection and defaults

- New installations and unversioned legacy settings migrate once to OpenRouter with `openrouter/free` selected.
- The migration is versioned. Once a user explicitly chooses Ollama, Gemini, or Hugging Face, subsequent launches preserve that selection.
- Each provider keeps its own model ID in `providers_config.<provider>.model`.
- Settings and provider credentials are stored locally in the ignored `config/settings.json`; public settings responses redact secrets and blank updates preserve saved credentials.

## Startup behavior

Each browser/app startup creates a new empty chat session. Existing sessions remain in the sidebar and in SQLite; the app does not automatically reopen the last conversation. Provider selection, model IDs, system prompt, profile, and appearance settings remain persisted independently of the new session.

## Provider behavior

### Ollama

- Model catalog: `GET {base_url}/api/tags`.
- Streaming chat: `POST {base_url}/api/chat`.
- Default URL: `http://localhost:11434`.

### OpenRouter

- OpenAI-compatible API with normalized `/api/v1` base URL.
- Model catalog: `GET /models`; the UI list is filtered to zero-priced models and `:free` variants, with `openrouter/free` always offered.
- Streaming chat: `POST /chat/completions`.

### Google AI Studio / Gemini

- Uses the current Gemini Interactions API at `/v1beta/interactions?alt=sse`.
- Authenticates with the `x-goog-api-key` header.
- Uses stateless requests (`store: false`) and includes the current chat transcript in the input.
- Model IDs are discovered from the Google model catalog and intersected with a maintained allowlist of model IDs currently published with a free tier.
- The free-tier allowlist must be updated when Google's pricing/model catalog changes; project-level rate limits and availability still depend on the user's account.

### Hugging Face Inference Providers

- Uses the OpenAI-compatible `https://router.huggingface.co/v1` chat-completions endpoint.
- Authenticates with a Hugging Face user access token.
- Model discovery reads `GET /v1/models` and offers exact `model_id:provider` choices only when a live provider reports `is_free: true`.
- Free status can be temporary and can change between catalog refreshes and requests.

## API endpoints

- `GET /api/settings`: public settings; secrets are redacted.
- `POST /api/settings`: partial settings update; blank secret fields preserve stored values.
- `GET /api/providers`: registered providers.
- `GET /api/providers/{provider_id}/models`: models discovered from that provider.
- `POST /api/chat`: streamed response using the active provider and selected model.
- `/api/sessions`: SQLite-backed chat sessions and messages.

## Persistence

SQLAlchemy manages sessions and messages in SQLite at `data/chat_history.db`. Each app startup creates a fresh session without deleting prior conversations.

## Security boundaries

The settings API does not return stored API keys. Keys are stored in the local ignored JSON settings file as plaintext, so protect the operating-system account and never commit `config/settings.json`. The app has no user authentication; keep it bound to localhost and do not expose it to untrusted networks.
