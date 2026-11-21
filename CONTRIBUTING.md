# Contributing

## Before making changes

1. Read [Project Principles](docs/PROJECT_PRINCIPLES.md).
2. Read [System Architecture](docs/ARCHITECTURE.md) and [Roadmap](docs/ROADMAP.md).
3. Read the module-specific contract for the area being changed.
4. Inspect the current implementation and tests before proposing a design.
5. Distinguish implemented behavior from accepted target architecture and planned work.

AI coding agents must also follow [AI Contribution Guide](docs/AI_CONTRIBUTION_GUIDE.md).

## Development workflow

1. Create or use a feature branch from the agreed base branch.
2. Keep provider implementations independent and register them through `core/providers/registry.py`.
3. Do not commit `config/settings.json`, `.env` files, API keys, chat history, or local databases.
4. Add or update tests for provider registration, model discovery, configuration migration, orchestration, and changed behavior.
5. Update README and architecture documentation whenever runtime behavior or module contracts change.
6. Open a pull request; do not merge until required checks pass.

## Architecture rules

- Keep provider-specific SDKs and payloads behind provider adapters.
- Do not bypass repository or permission boundaries.
- Models may request tool execution but cannot authorize or directly execute tools.
- Do not ingest files/conversations without explicit source permission.
- Do not publish AI Librarian reports without explicit user approval.
- Keep original source files separate from extracted or generated artifacts.
- Keep external connectors optional.
- Do not add speculative database tables unrelated to the approved milestone.

## Local checks

Run these commands from the repository root in an activated Python virtual environment:

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

For live smoke tests, start Ollama and confirm the provider model endpoint returns installed model tags. For a cloud provider, configure valid credentials and test model discovery and a short chat request. Do not expose or paste credentials in logs or issue comments.

## Provider checklist

- Implement the current `BaseLLMProvider` contract.
- Register a factory in `core/providers/registry.py`.
- Keep provider settings under `providers_config.<provider_id>`.
- Add tests for factory creation, model listing, streaming events, and error handling.
- Do not leak secrets through API responses, exceptions, or logs.
- Update the provider documentation and capability notes.

## Pull requests

- Keep changes focused and explain the architectural reason.
- Include tests and their observed results.
- Document known limitations and unverified assumptions.
- Do not merge until required checks pass.
