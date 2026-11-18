# Local AI Assistant

A Persian-first personal AI assistant with a FastAPI backend, lightweight browser UI, SQLite chat history, and pluggable LLM providers.

## Implemented features

- **Ollama (local):** discovers installed model names from Ollama's /api/tags endpoint and displays them in Settings.
- **OpenRouter (cloud):** uses the OpenAI-compatible Chat Completions API. The UI lists free models and offers openrouter/free as the default.
- **Provider-specific model selection:** Ollama and OpenRouter retain independent model choices.
- **Extensible provider registry:** providers are registered in core/providers/registry.py; the API and UI discover registered providers dynamically.
- **Streaming chat:** responses are streamed with Server-Sent Events.
- **Local persistence:** sessions and messages are stored in SQLite.
- **Secret-safe settings response:** API keys are not returned by GET /api/settings; leaving a secret field empty preserves the stored key.

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
- Ollama installed and running for local inference
- An OpenRouter API key for cloud inference

## Install and run

Clone the actual repository:

```powershell
git clone https://github.com/Aparsa40/local-ai-assistant.git
cd local-ai-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

On first run, the app copies config/settings.example.json to the ignored config/settings.json. Existing settings are migrated when loaded. The previous general Ollama model is preserved as the selected local model. OpenRouter defaults to openrouter/free.

## Configure providers

### Ollama

1. Start Ollama.
2. Install a model, for example: ollama pull llama3.2:1b.
3. Open Settings → Models and Providers.
4. Select Ollama. The model dropdown is populated from the running Ollama server.
5. Choose an installed model and save.

Default URL: http://localhost:11434.

### OpenRouter

1. Create an API key in your OpenRouter account.
2. Open Settings → Models and Providers.
3. Select OpenRouter, enter the API key, and choose a model.
4. Choose openrouter/free to let OpenRouter select an available free model for each request, or choose a specific free model from the refreshed catalog.

Default API URL: https://openrouter.ai/api/v1. Free model availability and rate limits are controlled by OpenRouter and can change. See the [OpenRouter free models guide](https://openrouter.ai/collections/free-models/) and [Free Models Router](https://openrouter.ai/openrouter/free).

## Extend providers

Implement BaseLLMProvider with chat_stream() and list_models(), then register a factory in core/providers/registry.py. The provider API and UI enumerate the registry, so adding a provider does not require adding another provider-specific branch to the orchestrator or hard-coding another UI option. Add tests for the factory, model discovery, and streaming behavior.

## Tests

Run from the repository root:

```powershell
python -m pip install pytest
python -m compileall -q core main.py
python -m pytest -q
```

GitHub Actions runs compile and unit-test checks on pushes and pull requests.

## Current scope and limitations

- GPT4All, RAG/ChromaDB, document ingestion, MCP, and external tool execution are not implemented yet; they remain future work.
- API keys are stored in the local ignored settings file as plaintext. Protect access to the machine.
- The application does not implement user authentication. Do not expose it to an untrusted network.
- Unit tests use mocks for provider-independent logic. Live Ollama/OpenRouter integration requires running services and valid credentials.

## License

MIT — see LICENSE.
