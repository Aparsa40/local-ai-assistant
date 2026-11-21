# Interface Manager

**Status:** Accepted target module contract; implementation is incremental.

## 1. Purpose

Interface Manager is the provider/model and external-interface control plane. It gives internal modules a stable way to discover capabilities, inspect connection state, and invoke models without depending on provider-specific SDKs or payloads.

It is infrastructure, not an AI reasoning agent.

## 2. Responsibilities

- Provider Registry: register supported provider adapters and their stable IDs.
- Model Catalog: expose normalized model metadata and exact provider model identifiers.
- Capability Registry: publish known/verified model capabilities and their evidence/freshness.
- Connection Manager: track configured endpoints, connectivity, health, and diagnostics.
- Credential integration: retrieve credentials through a protected credential service; never expose raw secrets to callers that do not need them.
- Request execution: normalize input requests, invoke the selected adapter, and normalize results/errors.
- Resilience policy: apply bounded timeouts, retry rules, and fallback eligibility where safe.
- Quota metadata: distinguish known limits, live remaining balance, estimated state, and unknown state.
- Connector/transport registration where required by the internal interface contract.

## 3. Explicit non-responsibilities

Interface Manager does not:
- Analyze the user's intent or decompose complex tasks.
- Decide which model is semantically best for a task.
- Validate factual correctness or compose final multi-model answers.
- Grant permissions to tools or data.
- Own conversation history, project knowledge, or original files.
- Silently change a user's selected provider/model.

Task planning belongs to Conversation Processing / AI Supervisor. Output review belongs to Response Validator & Composer. Permission decisions belong to Tool & Permission Manager.

## 4. Internal service contract

The exact Python package/API may evolve, but callers should depend on operations equivalent to:

| Operation | Purpose |
| --- | --- |
| `list_providers()` | Return registered provider identities and supported features. |
| `get_provider(provider_id)` | Resolve a provider adapter through the registry. |
| `list_models(provider_id, refresh=false)` | Return normalized catalog entries; optional refresh is explicit. |
| `get_model(provider_id, model_id)` | Resolve exact model metadata. |
| `get_capabilities(provider_id, model_id)` | Return capability metadata with source and freshness. |
| `get_connection_status(provider_id)` | Return configured/healthy/degraded/unavailable state without leaking secrets. |
| `validate_connection(provider_id)` | Perform a bounded diagnostic request where supported. |
| `invoke(request)` | Execute a normalized inference request and return normalized events/result. |

These are conceptual service operations, not a claim that all endpoints currently exist.

## 5. Normalized request and response

A normalized request should carry:
- provider_id and exact model_id;
- messages/context in a provider-neutral representation;
- generation parameters;
- requested output mode;
- supported tool definitions only when authorized by the caller;
- correlation/request ID and timeout policy.

A normalized response should carry:
- text/content and structured output when available;
- finish/termination reason;
- usage metadata when exposed;
- provider/model identity;
- timing and request correlation;
- warnings and normalized error details.

Do not fabricate missing usage, quota, or capability values. Represent unknown explicitly.

## 6. Capability metadata

Capability metadata should be typed and evidence-aware. Potential fields include:
- modalities: text, image, audio, video;
- context and output limits;
- streaming;
- tool/function calling;
- structured output / JSON mode;
- task suitability labels;
- embeddings or reranking support;
- pricing/free-tier metadata where maintained;
- account-specific availability and quota visibility.

Separate provider-level features from model-level features. A provider supporting a feature does not prove every model supports it.

Each field should indicate whether it is provider-reported, model-catalog-reported, curated, experimentally verified, or unknown, with a last-checked timestamp where practical.

## 7. Reliability behavior

- Use bounded timeouts.
- Retry only transient failures and only when the request is safe to retry.
- Do not blindly retry non-idempotent tool side effects.
- Treat authentication failure, quota exhaustion, rate limiting, model retirement, network failure, and malformed responses as distinct error classes.
- Fallback is a routing decision made with Conversation Processing; Interface Manager reports eligibility and failure facts.
- A quota value not exposed by a provider must remain unknown.

## 8. Security

- Never return raw API keys or tokens through public settings/model APIs.
- Redact credentials from exceptions and logs.
- Keep provider-specific authentication inside adapter/credential boundaries.
- Do not send conversation or file content to a provider unless the caller's data-access permissions allow it.
- Validate provider/model IDs against the registry; do not accept arbitrary executable adapter paths from the UI.

## 9. Current implementation mapping

The existing `core/providers/base.py`, `registry.py`, provider adapters, and `capabilities.py` form the current foundation. They are not yet the complete target Interface Manager described here. Preserve working provider behavior while introducing the normalized service boundary incrementally.

Related: [PROVIDER_SYSTEM.md](PROVIDER_SYSTEM.md), [MODEL_MANAGER.md](MODEL_MANAGER.md), [PERMISSIONS.md](PERMISSIONS.md).
