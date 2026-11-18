# Contributing

## Development workflow

1. Create a feature branch from main.
2. Keep provider implementations independent and register them through core/providers/registry.py.
3. Do not commit config/settings.json, .env files, API keys, chat history, or local databases.
4. Add or update tests for provider registration, model discovery, configuration migration, and orchestration.
5. Update README and architecture documentation whenever runtime behavior changes.
6. Open a pull request; do not merge until required checks pass.

## Local checks

Run these commands from the repository root in an activated Python virtual environment:

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest
python -m compileall -q core main.py
python -m pytest -q
```

For live smoke tests, start Ollama and confirm GET /api/providers/ollama/models returns installed model tags. For OpenRouter, configure a valid API key and confirm GET /api/providers/openrouter/models returns the free model catalog. Then send a short chat request through each provider separately.

## Provider checklist

- Implement BaseLLMProvider.chat_stream() and list_models().
- Register a factory in core/providers/registry.py.
- Keep provider settings under providers_config.<provider_id>.
- Add tests for factory creation, model listing, and error handling.
- Do not leak secrets through API responses or logs.
