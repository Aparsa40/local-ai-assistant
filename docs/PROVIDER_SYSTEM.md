# Provider System

**Status:** Provider adapter registry and six adapters implemented; normalized control-plane behavior is incremental.

## 1. Provider contract
Provider adapters implement `BaseLLMProvider`:
- `list_models()`: return exact model IDs visible through the adapter's discovery source.
- `chat_stream(messages, model, temperature)`: stream text from one explicitly selected model ID or supported provider router alias.

Adapters own vendor-specific authentication, endpoints, request/response formats, and transport parsing. They do not own task planning, permissions, or response validation.

## 2. Registry
Stable provider IDs are registered in `core/providers/registry.py`. Factories receive only the provider's configuration block. Do not accept arbitrary class paths or executable adapter names from the UI.

Current IDs: `ollama`, `openrouter`, `google_ai_studio`, `cloudflare_workers_ai`, `groq`, and `cohere`.

## 3. Discovery contract
- Discovery is explicit and bounded by Interface Manager timeouts.
- Return exact provider IDs; never invent, normalize away, or silently substitute identifiers.
- Account-scoped catalogs may return only models visible to the configured key/account.
- A provider-level catalog profile is not a live model list.
- A discovery failure must not erase the selected model.
- Preserve the difference between unknown provider, missing credentials, permission failure, rate limit, timeout, unavailable catalog, and model-not-found as adapter coverage improves.

## 4. Quota and usage
- Prefer provider-documented usage endpoints or response headers.
- Store only allowlisted non-secret telemetry.
- Distinguish account spend, requests, tokens, rate windows, plan allowances, and remaining quota.
- Never treat a published allowance as the live remaining balance.
- Missing telemetry is `unknown`, not zero.

## 5. Security
- Secrets stay server-side and are redacted from public settings/catalog responses.
- Do not log raw request headers, authorization values, or unfiltered provider error bodies.
- Never put credentials in prompts or model-visible context.
- Validate provider ID and model ID against the selected adapter/catalog boundary.

## 6. Required tests for an adapter
- Factory construction and missing/invalid credentials.
- Discovery success, empty catalog, pagination, and failure.
- Exact ID preservation and provider-specific filtering.
- Streaming events, error events, cancellation, and HTTP failures.
- Quota header parsing and explicit unknown behavior.
- Credential redaction and bounded timeouts.

Related: INTERFACE_MANAGER.md, OPERATOR_CATALOGS.md, PROVIDER_CAPABILITIES.md.
