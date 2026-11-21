# Local AI Assistant

A Persian-first personal AI workspace with a FastAPI backend, lightweight browser UI, SQLite chat history, and pluggable local/cloud LLM providers.

## Implemented features

- **Fresh chat on startup:** every app/browser launch creates a new empty session; previous conversations remain in the sidebar and SQLite.
- **Persistent settings:** provider, exact model ID, system prompt, profile, and appearance settings are independent of chat sessions and survive restarts.
- **OpenRouter (cloud):** OpenAI-compatible streaming API, free model catalog, and `openrouter/free` default.
- **Google AI Studio / Gemini:** Gemini Interactions API streaming, API-driven model discovery, and exact model ID selection.
- **Cloudflare Workers AI:** account-scoped inference, SSE streaming, and free-plan model discovery.
- **Groq:** OpenAI-compatible streaming chat, live model discovery, and tool-capable model choices.
- **Cohere:** Chat v2 streaming and live discovery of chat-compatible models.
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

### Cloudflare Workers AI

- Configure a Workers AI API token and your Cloudflare Account ID.
- The Workers Free plan includes 10,000 Neurons per day; remaining daily Neurons are not exposed by the inference endpoint.
- Model discovery is checked against the live account catalog and a conservative free-plan allowlist.
- Recommended model: `@cf/zai-org/glm-4.7-flash` for coding, analysis, multilingual chat, and tool-oriented tasks.

Links: [REST API](https://developers.cloudflare.com/workers-ai/get-started/rest-api/), [Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/).

### Groq

- Create an API key in [Groq Console](https://console.groq.com/keys).
- The model catalog is refreshed from the authenticated Groq API.
- Recommended models: `openai/gpt-oss-20b` for everyday chat and `openai/gpt-oss-120b` or `qwen/qwen3.8-27b` for coding and analysis.
- Free-tier limits are organization- and model-specific; consult the [rate-limit page](https://console.groq.com/docs/rate-limits) and your [Limits dashboard](https://console.groq.com/settings/limits).

### Cohere

- Create a free trial API key in [Cohere Dashboard](https://dashboard.cohere.com/api-keys).
- Chat model discovery uses the Cohere `/v1/models` catalog and filters to non-deprecated chat models.
- Trial keys are limited to 1,000 API calls per month and 20 Chat requests per minute per model.
- Recommended model: `command-r7b-12-2024` for general chat and translation; Command models can be selected for deeper analysis.

Links: [Model catalog](https://docs.cohere.com/v2/reference/list-models), [Rate limits](https://docs.cohere.com/docs/rate-limits).

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
- Cloudflare, Groq, and Cohere quotas and model availability can change; quota remaining is shown as unknown when the provider does not expose a live balance.
- API keys are stored in the local ignored settings file as plaintext. Protect access to the machine.
- The application does not implement user authentication. Do not expose it to an untrusted network.

## License

MIT — see LICENSE.
