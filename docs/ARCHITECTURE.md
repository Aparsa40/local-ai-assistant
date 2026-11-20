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
       ├── CloudflareWorkersAIProvider
       ├── GroqProvider
       └── CohereProvider
```

## Provider contract

Every provider implements BaseLLMProvider:

- `chat_stream(messages, model, temperature)`: async generator of text chunks.
- `list_models()`: async retrieval of exact model identifiers selectable in the UI.

Provider construction is delegated to `core/providers/registry.py`. The API returns registered provider IDs and calls the selected provider's `list_models()` method. The UI discovers the registry dynamically.

## Model selection and defaults

- New installations and unversioned legacy settings migrate once to OpenRouter with `openrouter/free` selected.
- The migration is versioned. A legacy Hugging Face selection is migrated to OpenRouter because that provider has been retired; supported explicit provider selections are preserved.
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

### Cloudflare Workers AI

- Uses the account-scoped Workers AI REST inference endpoint and requires an API token plus Account ID.
- Model discovery uses the Cloudflare AI model-search endpoint and intersects the live catalog with a conservative free-plan allowlist.
- Workers Free includes 10,000 Neurons/day. Remaining Neurons are not returned by the inference endpoint and are represented as unknown.

### Groq

- Uses the OpenAI-compatible Chat Completions API at `https://api.groq.com/openai/v1`.
- Model discovery reads the authenticated `/models` catalog and filters to curated chat models.
- Streaming uses SSE. Tool calling is supported by the selected Groq models.
- Free-tier limits vary by organization and model; the account Limits dashboard is authoritative.

### Cohere

- Uses the native Cohere Chat v2 endpoint `/v2/chat` with SSE streaming.
- Model discovery reads `/v1/models?endpoint=chat` and excludes deprecated models.
- Trial keys are limited to 1,000 API calls/month and 20 Chat requests/minute/model. The API does not expose remaining monthly calls.

### Capability metadata

- `core/providers/capabilities.py` exposes context windows, task suitability, streaming, tool calling, free-tier eligibility, quota allowances, and quota-status semantics.
- `GET /api/providers/{provider_id}/capabilities` serves the capability manifest. This is groundwork for a future Architect; automatic routing is not yet enabled.

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
