# Provider System

**Status:** Accepted adapter contract; provider-specific integrations are implemented incrementally.

## 1. Purpose

The Provider System isolates vendor-specific APIs, authentication, model discovery, streaming protocols, quota semantics, and error formats behind a stable adapter contract used by Interface Manager.

A provider is an integration endpoint/operator. A model is a specific inference offering exposed through a provider. Do not conflate the two.

## 2. Provider adapter contract

Each adapter should implement the common operations required by the application, conceptually:

- initialize from validated provider configuration;
- discover available model identifiers when the provider supports discovery;
- perform inference/streaming using a normalized request;
- expose bounded health/connection diagnostics where supported;
- normalize provider errors and usage metadata;
- expose provider-specific capability facts without leaking vendor payloads into domain modules.

The current repository's `BaseLLMProvider` contract includes streaming chat and model listing. Expand it compatibly as the Interface Manager contract is implemented.

## 3. Provider registry

- Provider IDs are stable machine identifiers (for example, `ollama`, `openrouter`, `google_ai_studio`, `cloudflare_workers_ai`, `groq`, and `cohere`).
- Registry entries map IDs to adapter factories and metadata.
- User-facing display names are not identifiers.
- Provider registration must be explicit and testable.
- A provider adapter must not import or mutate conversation/database internals.

## 4. Model discovery

- Preserve exact model IDs returned by providers.
- Distinguish live-discovered catalog entries from curated allowlists and local installed models.
- Do not assume that a listed model is enabled for a specific account.
- Do not infer free-tier status from a model name alone.
- Cache catalog results with a timestamp and refresh policy.
- If discovery is unavailable, show the last-known catalog with its age or report that discovery is unavailable.

## 5. Provider configuration and credentials

Configuration may include endpoint/base URL, account/tenant identifiers, and credential references. Secrets must be handled through the protected credential boundary.

Current implementation note: the repository currently stores local provider settings in an ignored JSON settings file, and its credential protection is not yet a full encrypted vault. Do not describe the current storage as encrypted. A future credential service should support secure storage, redaction, rotation, and explicit removal.

## 6. Normalized errors

Adapters should map provider failures into stable categories:
- authentication/authorization;
- invalid configuration;
- model not found or retired;
- quota exhausted;
- rate limited;
- network/timeout;
- provider unavailable;
- unsupported capability;
- malformed response;
- unknown provider error.

Preserve a safe diagnostic message and correlation ID. Never expose tokens, raw secret-bearing headers, or sensitive request bodies.

## 7. Quota and availability semantics

Represent separately:
- published plan allowance;
- account-specific configured limit;
- live remaining quota;
- rate-limit response state;
- unknown/unavailable quota state.

Unknown is not zero and is not unlimited. Provider limits and model availability change; documentation must include a last-verified date for time-sensitive recommendations.

## 8. Adding a provider

1. Read this contract and the project principles.
2. Inspect the current base adapter and registry.
3. Implement the smallest compatible adapter.
4. Add tests for construction, discovery, streaming, errors, credential redaction, and configuration migration where relevant.
5. Update provider capability documentation and README.
6. Do not introduce provider-specific logic into Conversation Processing or UI routing.
7. Confirm no secrets or local settings are committed.

Related: [INTERFACE_MANAGER.md](INTERFACE_MANAGER.md), [MODEL_MANAGER.md](MODEL_MANAGER.md), [PROVIDER_CAPABILITIES.md](PROVIDER_CAPABILITIES.md).
