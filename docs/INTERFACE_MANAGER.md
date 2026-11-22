# Interface Manager

**Status:** Provider-neutral service boundary, persistent operator/live catalogs, provider diagnostics, quota snapshots, and operational report implemented incrementally.

## 1. Purpose

Interface Manager is the provider/model control plane. It gives internal modules a stable way to discover providers and models, inspect capability metadata, perform bounded connection diagnostics, and invoke models without depending on provider-specific SDKs or payloads.

It is infrastructure, not an AI reasoning agent.

## 2. Responsibilities

- Provider Registry: expose registered provider adapters and stable IDs.
- Operator Catalog: expose provider-level discovery policy, account requirements, task tags, quota visibility, and authoritative documentation links without requiring network access.
- Model Catalog: discover and preserve exact provider model identifiers.
- Capability Registry: expose known capability metadata and its evidence/freshness.
- Connection Diagnostics: report bounded connectivity probes without exposing credentials.
- Credential integration: use the current local settings boundary; a dedicated encrypted credential vault remains future work.
- Request execution: route normalized application calls to provider adapters.
- Error normalization: expose safe, provider-neutral error categories.
- Resilience policy: add bounded timeouts and, in later increments, safe retry/fallback policies.
- Quota metadata: distinguish known limits, live remaining balance, and unknown state.

## 3. Explicit non-responsibilities

Interface Manager does not:
- Analyze user intent or decompose complex tasks.
- Decide which model is semantically best for a task.
- Validate factual correctness or compose final multi-model answers.
- Grant permissions to tools or data.
- Own conversation history, project knowledge, or original files.
- Silently change a user's selected provider/model.

Task planning belongs to Conversation Processing / Agent Runtime / Supervisor. Output review belongs to Response Validator & Composer. Permission decisions belong to Tool & Permission Manager.

## 4. Current implemented service operations

| Operation | Current behavior |
| --- | --- |
| list_providers() | Returns registered provider IDs, display names, and whether capability metadata exists. |
| get_capabilities(provider_id) | Returns the local capability manifest for a registered provider. |
| get_provider_catalog(provider_id) | Returns the local operator profile and curated model metadata; performs no network request. |
| get_quota_status(provider_id) | Returns observed provider quota telemetry when available; otherwise an explicit not-exposed/unknown state. |
| list_models(provider_id) | Performs bounded provider discovery; API/UI read paths use the persisted catalog instead of triggering network I/O. |
| check_connection(provider_id) | Probes model-catalog access and reports reachable/unreachable, model count, timestamp, and a safe error category. |
| stream_chat(provider_id, messages, model) | Streams inference through the selected provider adapter behind the service boundary. |

HTTP endpoints:
- GET /api/providers
- GET /api/providers/{provider_id}/capabilities
- GET /api/providers/{provider_id}/catalog
- GET /api/providers/{provider_id}/models (persisted read)
- POST /api/providers/{provider_id}/catalog/sync (explicit live refresh)
- GET /api/providers/{provider_id}/quota
- POST /api/providers/{provider_id}/connection
- GET /api/operational-report
- POST /api/chat uses Interface Manager for provider streaming.

The Provider settings panel exposes a “Save and check connection” action that persists the edited settings, probes the provider catalog, and persists the model IDs returned by that same probe. Manual catalog refresh is a separate action and does not run during ordinary UI reads.

The connection endpoint currently performs a **model-catalog probe**. A successful catalog request proves that the provider's discovery endpoint is reachable; it does not prove that a subsequent inference request will succeed. The API must not label this as a full inference health check. The endpoint is POST-only because it performs discovery and persists runtime/catalog state. The accepted Provider & Model Intelligence design coordinates local Ollama startup and report generation around this service boundary; it must not move provider API implementations out of adapters.

## 5. Remaining target service contract

The following operations are accepted targets but are not fully implemented yet:

| Operation | Target behavior |
| --- | --- |
| get_model(provider_id, model_id) | Resolve normalized model metadata and lifecycle state. |
| get_connection_status(provider_id) | Return cached/observed connection state with freshness. |
| invoke(request) | Accept a typed provider-neutral request and return normalized events/results. |
| Catalog refresh/cache | Implemented incrementally through SQLite live-model records, first/last-seen timestamps, active/retired state, and sync history. |
| Capability evidence | Track provider-reported, catalog-reported, curated, experimentally verified, or unknown values. |
| Resilience policy | Add bounded inference timeouts and carefully classified retry behavior. |
| Credential service | Provide encrypted storage, rotation, explicit removal, and redaction. |
| Quota telemetry | Normalize live headers/telemetry where providers expose it; otherwise preserve unknown. |

## 6. Normalized request and response target

A normalized request should carry:
- provider_id and exact model_id;
- provider-neutral messages/context;
- generation parameters and requested output mode;
- tool definitions only when authorized by the caller;
- correlation/request ID and timeout policy.

A normalized response should carry:
- text/content and structured output when available;
- finish reason and usage metadata when exposed;
- provider/model identity;
- timing and request correlation;
- warnings and normalized error details.

Do not fabricate missing usage, quota, or capability values. Represent unknown explicitly.

## 7. Capability metadata

Operator profiles are local static metadata and are not a substitute for live model discovery. The Settings UI must display them even when discovery is unavailable. Exact model IDs should come from live discovery when supported; curated fallbacks must be visibly labeled and must never be represented as account-verified.

Capability metadata should distinguish provider-level facts from model-level facts. Potential fields include modalities, context/output limits, streaming, tool/function calling, structured output, task suitability, embeddings/reranking, pricing, and account-specific availability.

Each field should indicate its evidence class and last-checked time where practical. A provider supporting a feature does not prove every model supports it.

## 8. Reliability behavior

- Catalog discovery uses a bounded timeout.
- Authentication failure, quota exhaustion, rate limiting, model retirement, network failure, and malformed responses should be distinct normalized categories as adapter coverage improves.
- Current safe errors intentionally avoid returning raw provider exception text to API clients.
- Inference-stream timeout, retry, and fallback policies remain future work.
- Fallback is a routing decision made by Conversation Processing / Agent Runtime; Interface Manager reports facts and executes the selected request.
- Unknown quota must remain unknown.

## 9. Security

- Never return raw API keys or tokens through public settings/model APIs.
- Do not expose raw provider exception text that may contain sensitive request details.
- Keep provider-specific authentication inside adapter/configuration boundaries.
- Do not send conversation or file content to a provider unless the caller's data-access policy permits it.
- Validate provider IDs against the registry; do not accept arbitrary executable adapter paths from the UI.

Current local provider credentials remain in the ignored settings file and are not stored in a dedicated encrypted vault. The application also does not yet implement user authentication; do not expose it to untrusted networks.

## 10. Implementation mapping

- core/interface_manager.py: provider-neutral service boundary.
- core/providers/base.py: current provider adapter contract.
- core/providers/registry.py: provider factories and registration.
- core/providers/capabilities.py: current capability/quota metadata.
- core/providers/operator_catalog.py: local operator-level catalog and discovery/quota policy.
- core/orchestrator.py: explicit user-selected provider/model resolution.
- main.py: API boundary; provider discovery and chat streaming delegate through Interface Manager.
- tests/test_interface_manager.py: isolated service contract tests.

This is an incremental implementation. Do not describe the complete Model Manager, Updater, credential vault, automatic routing, or full health monitoring as shipped.

Related: PROVIDER_MODEL_INTELLIGENCE.md, OPERATOR_CATALOGS.md, PROVIDER_SYSTEM.md, MODEL_MANAGER.md, AGENT_RUNTIME.md, PERMISSIONS.md.


## 8. Persistent catalog storage

`core/catalog_storage.py` is the repository layer for the Interface Manager's catalog read models. The SQLAlchemy schema in `core/database.py` now includes:

- `operator_catalogs` and `operator_model_profiles` for repository-owned operator manifests and curated model evidence.
- `live_model_catalog` for provider-reported exact model IDs, keyed by `(provider_id, model_id)`.
- `provider_runtime_status` and `model_runtime_status` for separately observed connection and inference facts.
- `provider_quota_snapshots` for timestamped provider quota responses.
- `catalog_sync_history` for successful, failed, and ambiguous-empty sync outcomes.

Startup uses `Base.metadata.create_all()` to add these tables without replacing existing chat/profile tables, then seeds the version-controlled operator manifests. Existing SQLite data is preserved.

The UI reads the persisted catalog. A provider API call is made only by the connection probe or explicit catalog-sync action. A failed sync never clears last-known-good records; ambiguous empty responses are also preserved when a prior catalog exists.
