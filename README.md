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
- **Ollama:** local model discovery and streaming inference; explicit connection can reuse an active server or start the installed CLI when auto-start is enabled and the endpoint is loopback HTTP.
- **Provider & Model Intelligence:** persisted provider intelligence reports, Ollama model metadata enrichment, evidence-aware task suitability, and explicit freshness/unknown states.
- **Local Model Runtime:** implemented provider-neutral runtime lifecycle management with Ollama as the first adapter, installed/loaded model inspection, explicit load/unload, owned-process shutdown, SQLite lifecycle history, bounded operations, and read-only status/snapshot APIs. CI passes (109 tests); Windows runtime connectivity and inventory were verified. Live model loading remains hardware-constrained and unverified on the observed 4 GB RAM / mechanical-HDD machine; see [Local Model Runtime validation](docs/LOCAL_MODEL_RUNTIME.md#14-windows-smoke-validation-and-environment-constraints).
- **Provider-specific model selection:** each provider retains its own selected model.
- **Interface Manager foundation:** provider listing, operator-level catalog metadata, capability access, bounded model discovery, safe provider-neutral errors, quota visibility, and chat streaming through one service boundary.
- **Operator Capability Catalog:** version-controlled provider manifests describe service type, discovery method, credential requirements, official documentation, task tags, and published free-tier policy separately from exact model IDs.
- **Persistent Live Model Catalogs:** each provider has an independent SQLite namespace keyed by `(provider_id, model_id)`; active/retired state and first/last-seen timestamps are retained.
- **Catalog synchronization:** the connection probe persists the model IDs it already discovered; manual refresh is a separate explicit action. Failed or ambiguous-empty refreshes preserve the last known-good catalog.
- **Operational report:** `/api/operational-report` exposes provider reachability, live model inventory, model inference observations, quota snapshots, and sync history as a shared machine-readable read model.
- **Intelligence reports:** `/api/intelligence/reports/latest` reads the latest persisted analysis; `/api/intelligence/reports/offline` builds a report from SQLite only, without network calls or process startup.
- **Connection diagnostics:** the Provider settings panel can save the current configuration and probe model-catalog reachability; it does not claim that inference is fully healthy.
- **Quota diagnostics:** OpenRouter key usage can be read through its key endpoint; Groq/Cohere telemetry is shown only when response headers have actually been observed. Other unavailable balances remain unknown.
- **Secret-safe settings responses:** API keys/tokens are redacted from browser-facing settings responses; current local credential storage is not an encrypted vault.
- **Storage Manager & Repository Services:** centralized SQLite lifecycle, explicit transaction boundaries, and domain repositories for catalog, runtime, profile, sessions, messages, and memories.
- **Conversation & Profile Services:** application-owned conversation/message persistence and profile/avatar validation, now guarded by explicit permission contexts.
- **Memory & Context Services:** scoped candidate/active memory lifecycle, provenance, retention, deterministic retrieval, bounded conversation history, and token-budgeted context assembly. Memory access remains default-deny unless an explicit policy is injected.
- **Permission Manager (Phase 5 foundation merged; final integration/acceptance in progress):** typed subjects/resources/operations/scopes, exact-scope persisted grants, expiry/revocation, default-deny decisions, one-time action-bound approvals, and redacted append-only audit events.
- **Tool Registry & Runtime (Phase 5 foundation merged; production tool registration and orchestration integration are future work):** explicit versioned tool registration, restricted JSON-schema validation, risk classification, approval gates, async bounded execution, output limits, and normalized errors. No arbitrary shell/Python or unrestricted file/network tools are registered.
- **Local API boundary:** settings, provider, runtime, profile, session, and chat APIs require loopback clients and a fixed local single-user principal. This is not user authentication; do not expose the application through a LAN, reverse proxy, or public network.
- **SQLite persistence:** chat sessions, messages, profile data, operator manifests, curated model profiles, live model catalogs and model metadata, provider/model runtime status, quota snapshots, catalog sync history, intelligence reports, permission grants, approval requests, and redacted audit events are stored locally. Phase 4 now includes ordered SQLite schema migrations (`0001`–`0004`) for Knowledge and legacy schema evolution; PostgreSQL migrations are not implemented.

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
├── core/runtime/            # local runtime adapters, lifecycle manager and persistence
├── core/storage/            # centralized Storage Manager and SQLite adapter
├── core/repositories/       # domain-owned persistence repositories
├── core/conversations/     # conversation and message services
├── core/profiles/          # profile service
├── core/memory/            # scoped memory lifecycle and retrieval
├── core/context/           # bounded request context assembly
├── core/permissions/       # default-deny Permission Manager and approval/audit services
├── core/tools/             # Tool Registry and bounded Tool Runtime
├── core/provider_intelligence.py # local runtime lifecycle and provider/model reports
├── core/catalog_storage.py  # durable operator/live catalog and report repository
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
- [Local Model Runtime](docs/LOCAL_MODEL_RUNTIME.md)
- [Operator Catalogs and Discovery Policy](docs/OPERATOR_CATALOGS.md)
- [Catalog Storage Schema](docs/CATALOG_STORAGE.md)
- [Provider system](docs/PROVIDER_SYSTEM.md)
- [Model Manager](docs/MODEL_MANAGER.md)
- [Phase 5 execution plan](docs/PHASE_05_EXECUTION_PLAN.md)
- [Permissions](docs/PERMISSIONS.md)
- [Tool Runtime](docs/TOOL_RUNTIME.md)
- [Knowledge Storage](docs/KNOWLEDGE_STORAGE.md)
- [AI orchestration](docs/AI_ORCHESTRATION.md)
- [Agent Runtime](docs/AGENT_RUNTIME.md)

The documents distinguish **Implemented**, **Accepted**, and **Planned** capabilities. Phase 4 WP-4.1–WP-4.7 is implemented and merged through PR #16 (`923ad244d91425cca50a64b4c683f62aa53b7fc0`); CI passed 228 tests. Phase 5 PR #15 is merged, but the phase is not yet declared complete: grant/approval administration surfaces, Knowledge authorization integration, destructive-action approval coverage, and final security regression/documentation acceptance remain. Read the relevant module contract before changing that area.

## Requirements

- Python 3.10+
- Ollama installed when using local inference; the app can start its local server on explicit connection when auto-start is enabled
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

Open **Settings → Models and Providers**, select a provider, enter its key/token where required, then use **Save and check connection** to persist settings and sync the first live catalog. Later, use **دریافت / همگام‌سازی کاتالوگ** for an explicit refresh. The UI reads model lists from SQLite and preserves the last known-good catalog when a refresh fails.

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

1. Install Ollama and pull a model, for example: `ollama pull llama3.2:1b`.
2. Select Ollama and use **Save, connect and discover models**. If the local server is not running, the app attempts to start it when Auto Start is enabled.
3. Auto Start is limited to loopback HTTP endpoints. Remote Ollama endpoints are never started by the local application.

Default URL: `http://localhost:11434`.

## Settings and credentials

The complete example is in `config/settings.example.json`. The real `config/settings.json` is ignored by Git. Never commit it, API keys, tokens, local databases, or chat history.

Current local credential storage is not an encrypted vault. The API now rejects non-loopback clients, but the fixed local principal is not authentication and does not protect against other processes/users on the same machine. Do not expose the development server through a LAN, reverse proxy, or public network.

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
- Production tool handlers and model/agent tool-call orchestration; the registry/runtime infrastructure exists, but Phase 6 must supply the agent execution integration.
- Operational grant administration and approval review endpoints/UI, and complete approval mediation for direct destructive API operations (Phase 5 remaining work).
- Central Permission Manager adapter integration for Knowledge reads/writes (Phase 5 remaining work).
- External connector framework and Discord synchronization.
- Automated document ingestion, AI Librarian, approved shared knowledge publication, and model-private memory lifecycle.
- PostgreSQL migration adapter; current versioned migration implementation targets SQLite only.
- Authentication and hosted multi-user security.

The current chat path still uses manual provider/model selection. Agent Runtime, automatic task routing, and Multi-Agent execution are not implemented yet. The application does not implement user authentication. Do not expose the current development server to an untrusted network.

## License

MIT — see [LICENSE](LICENSE).
