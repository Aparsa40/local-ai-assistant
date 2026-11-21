# Local AI Assistant

A Persian-first, local-first AI workspace with a FastAPI backend, lightweight browser UI, SQLite persistence, and replaceable local/cloud model providers.

The long-term direction is a provider-agnostic assistant with controlled knowledge access, online/offline execution paths, permissioned tools and connectors, and an auditable AI Librarian workflow. The current implementation is an earlier foundation; planned architecture must not be mistaken for shipped functionality.

## Current implemented foundation

- **Fresh chat on startup:** each app/browser launch creates a new empty session; previous conversations remain available in the sidebar and SQLite.
- **Persistent settings:** provider, exact model ID, system prompt, profile, and appearance settings persist independently of chat sessions.
- **OpenRouter:** OpenAI-compatible streaming API, model catalog, and `openrouter/free` default.
- **Google AI Studio / Gemini:** Gemini Interactions API streaming and model discovery.
- **Cloudflare Workers AI:** account-scoped inference, SSE streaming, and model discovery.
- **Groq:** OpenAI-compatible streaming chat and model discovery.
- **Cohere:** Chat v2 streaming and model discovery.
- **Ollama:** local model discovery and streaming inference.
- **Provider-specific model selection:** each provider retains its own selected model.
- **Interface Manager foundation:** provider listing, capability access, bounded model discovery, safe provider-neutral errors, and chat streaming through one service boundary.
- **Connection diagnostics:** the Provider settings panel can save the current configuration and probe model-catalog reachability; it does not claim that inference is fully healthy.
- **Secret-safe settings responses:** API keys/tokens are redacted from browser-facing settings responses; current local credential storage is not an encrypted vault.
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
├── core/interface_manager.py # provider-neutral service boundary
├── data/                    # local SQLite database (git-ignored)
├── docs/                    # architecture, principles, module contracts, roadmap
├── static/
├── tests/
├── main.py
└── requirements.txt
```

## Architecture and roadmap

Start with the documentation index: [docs/README.md](docs/README.md).

Important documents:
- [Project principles](docs/PROJECT_PRINCIPLES.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [AI contribution/delegation guide](docs/AI_CONTRIBUTION_GUIDE.md)
- [Interface Manager](docs/INTERFACE_MANAGER.md)
- [Provider system](docs/PROVIDER_SYSTEM.md)
- [Model Manager](docs/MODEL_MANAGER.md)
- [Permissions](docs/PERMISSIONS.md)
- [AI orchestration](docs/AI_ORCHESTRATION.md)
- [Agent Runtime](docs/AGENT_RUNTIME.md)

The documents distinguish **Implemented**, **Accepted**, and **Planned** capabilities. Read the relevant module contract before changing that area.

## Requirements

- Python 3.10+
- Ollama installed and running only when using local inference
- API credentials for whichever cloud providers you choose

## Install and run

```powershell
git clone https://github.com/Aparsa40/local-ai-assistant.git
cd local-ai-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

On first run, the app copies `config/settings.example.json` to the ignored `config/settings.json`. Existing unversioned settings migrate once to OpenRouter as the default provider. After that migration, explicitly selected providers are preserved. Each app startup creates a new chat session while retaining earlier sessions.

## Configure providers

Open **Settings → Models and Providers**, select a provider, enter its key/token where required, refresh its model list, select the exact model ID, and save.

### OpenRouter

- API key: create one in your OpenRouter account.
- Default model: `openrouter/free` (router-selected free model).
- The model list is filtered according to the current catalog/pricing logic.

Links: [OpenRouter API keys](https://openrouter.ai/keys), [Free Models](https://openrouter.ai/collections/free-models/).

### Google AI Studio / Gemini

- API key: create it in [Google AI Studio](https://aistudio.google.com/app/apikey).
- Refresh the model catalog to obtain exact model IDs available to the key and supported by the maintained allowlist.
- Availability and rate limits depend on the Google AI Studio project and can change.

### Cloudflare Workers AI

- Configure a Workers AI API token and Cloudflare Account ID.
- The Workers Free plan allowance and live remaining balance are different concepts; remaining quota may be unknown when the API does not expose it.
- Model discovery uses the account catalog and a maintained allowlist.

Links: [REST API](https://developers.cloudflare.com/workers-ai/get-started/rest-api/), [Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/).

### Groq

- Create an API key in [Groq Console](https://console.groq.com/keys).
- The model catalog is refreshed from the authenticated API.
- Limits vary by organization and model; consult the [rate-limit page](https://console.groq.com/docs/rate-limits) and your [Limits dashboard](https://console.groq.com/settings/limits).

### Cohere

- Create a trial API key in [Cohere Dashboard](https://dashboard.cohere.com/api-keys).
- Chat model discovery uses the Cohere model catalog and filters deprecated/non-chat models.
- Trial quotas and model availability may change; consult the [model catalog](https://docs.cohere.com/v2/reference/list-models) and [rate limits](https://docs.cohere.com/docs/rate-limits).

### Ollama

1. Start Ollama.
2. Pull a model, for example: `ollama pull llama3.2:1b`.
3. Select Ollama and choose an installed model.

Default URL: `http://localhost:11434`.

## Settings and credentials

The complete example is in `config/settings.example.json`. The real `config/settings.json` is ignored by Git. Never commit it, API keys, tokens, local databases, or chat history.

Current local credential storage is not an encrypted vault. Protect access to the operating-system account and do not expose the development server to untrusted networks.

## Extend providers

Implement the current provider contract in `core/providers/base.py`, register the adapter in `core/providers/registry.py`, and add tests for construction, model discovery, streaming, error handling, and credential redaction. Follow [PROVIDER_SYSTEM.md](docs/PROVIDER_SYSTEM.md) and [AI_CONTRIBUTION_GUIDE.md](docs/AI_CONTRIBUTION_GUIDE.md).

## Tests

```powershell
python -m pip install pytest
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

GitHub Actions runs JavaScript syntax validation, Python compilation, and unit tests.

## Current limitations

The following target capabilities are **not yet implemented as complete systems**:
- Full Model Manager/catalog persistence, scheduled Model & Provider Updater, encrypted credential vault, comprehensive health monitoring, and inference retry/fallback policies.
- Automatic task-based routing and LLM Supervisor.
- Unified Conversation Processing with explicit online/offline engines.
- Response Validator & Composer.
- Permission Manager and permissioned Tool Runtime.
- External connector framework and Discord synchronization.
- Document ingestion, AI Librarian, approved shared knowledge, and model-private memory lifecycle.
- Full repository/migration architecture for SQLite and PostgreSQL.
- Authentication and hosted multi-user security.

The current chat path still uses manual provider/model selection. Agent Runtime, automatic task routing, and Multi-Agent execution are not implemented yet. The application does not implement user authentication. Do not expose the current development server to an untrusted network.

## License

MIT — see [LICENSE](LICENSE).
