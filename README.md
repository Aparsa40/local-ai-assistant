# Local AI Assistant

A Persian-first personal AI workspace with a FastAPI backend, lightweight browser UI, SQLite chat history, and pluggable local/cloud LLM providers.

## Implemented features

- **Fresh chat on startup:** every app/browser launch creates a new empty session; previous conversations remain in the sidebar and SQLite.
- **Persistent settings:** provider, exact model ID, system prompt, profile, and appearance settings are independent of chat sessions and survive restarts.
- **OpenRouter (cloud):** OpenAI-compatible streaming API, free model catalog, and `openrouter/free` default.
- **Google AI Studio / Gemini:** Gemini Interactions API streaming, API-driven model discovery, and exact model ID selection.
- **Hugging Face Inference Providers:** streaming chat completions and discovery of model/provider combinations currently marked free by the catalog.
- **Ollama (local):** discovers installed model tags and streams local chat responses.
- **Provider-specific model selection:** each provider retains its own selected model.
- **Secret-safe settings:** API keys/tokens are never returned to the browser; blank secret fields preserve existing credentials.
- **SQLite persistence:** chat sessions, messages, and profile data are stored locally.

## Project structure

```text
local-ai-assistant/
├── .github/workflows/ci.yml
├── config/settings.example.json
├── core/providers/          # provider contract, adapters and registry
├── core/config_manager.py
├── core/database.py
├── core/orchestrator.py
├── data/                    # local SQLite database (git-ignored)
├── docs/
├── static/
├── tests/
├── main.py
└── requirements.txt
```

## Requirements

- Python 3.10+
- Ollama installed and running only when using local inference
- API credentials for whichever cloud providers you choose

## Install and run

```powershell
git clone https://github.com/Aparsa40/local-ai-assistant.git
cd local-ai-assistant
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

On first run, the app copies `config/settings.example.json` to the ignored `config/settings.json`. Existing unversioned settings migrate once to OpenRouter as the default provider. After that migration, any provider the user explicitly selects is preserved. Each app startup creates a new chat session while retaining all earlier sessions.

## Configure providers

Open **Settings → Models and Providers**, select a provider, enter its key/token, refresh its model list, select the exact model ID, and save.

### OpenRouter

- API key: create one in your OpenRouter account.
- Default model: `openrouter/free` (router-selected free model).
- The model list includes currently free/zero-priced chat models.

Links: [OpenRouter API keys](https://openrouter.ai/keys), [Free Models](https://openrouter.ai/collections/free-models/).

### Google AI Studio / Gemini

- API key: create it in [Google AI Studio](https://aistudio.google.com/app/apikey).
- Default model ID in the example: `gemini-3.8-flash`.
- Refresh the model catalog to get exact model IDs that are both available to your API key and present in the maintained free-tier allowlist.
- The initial free-tier choices are `gemini-3.8-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-flash`, and `gemini-2.5-flash-lite`, based on Google's published [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). Availability and rate limits still depend on your Google AI Studio project.
- The adapter uses the current Interactions API and streaming events.

### Hugging Face Inference Providers

- Create a user access token with the required inference permissions in [Hugging Face Settings → Access Tokens](https://huggingface.co/settings/tokens).
- The model catalog returns exact `model_id:provider` values only when a live inference provider currently reports `is_free: true`.
- Free status may be a temporary promotion. The app refreshes the catalog from Hugging Face rather than hard-coding a list of models.
- Hugging Face Inference Providers may require paid credits for models/providers that are not currently marked free.

Links: [Inference Providers Chat Completion](https://huggingface.co/docs/inference-providers/tasks/chat-completion), [Hub API model catalog](https://huggingface.co/docs/inference-providers/hub-api).

### Ollama

1. Start Ollama.
2. Pull a model, for example: `ollama pull llama3.2:1b`.
3. Select Ollama and choose an installed model.

Default URL: `http://localhost:11434`.

## Settings example

The complete example is in `config/settings.example.json`. Copy only the provider blocks you need into your existing ignored `config/settings.json`, or enter keys directly through the Settings UI. Never commit the real `settings.json` file.

## Extend providers

Implement `BaseLLMProvider` with `chat_stream()` and `list_models()`, then register a factory in `core/providers/registry.py`. Add tests for provider construction, model discovery, streaming events, and credential handling.

## Tests

```powershell
python -m pip install pytest
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

GitHub Actions runs JavaScript syntax validation, Python compilation, and unit tests.

## Current scope and limitations

- The task-based architect/router and automatic tool selection are not implemented yet; the current mode remains manual provider/model selection.
- MCP and external app connectors with permission management remain future work.
- Documents, long-term knowledge memory, RAG, and cache management remain future work.
- Google AI Studio free-tier IDs are maintained against Google's public pricing page; update the allowlist when pricing or model availability changes.
- Hugging Face free model/provider availability can change; the app uses the live catalog's `is_free` metadata.
- API keys are stored in the local ignored settings file as plaintext. Protect access to the machine.
- The application does not implement user authentication. Do not expose it to an untrusted network.

## License

MIT — see LICENSE.
