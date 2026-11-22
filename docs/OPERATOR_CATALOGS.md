# Operator Catalogs and Discovery Policy

**Status:** Operator-level catalog manifest implemented; provider model discovery remains adapter-specific and optional.

## 1. Why operator catalogs exist

The application must not confuse three different things:

1. **Operator profile:** what the provider platform offers at a platform level, which APIs exist, what credentials/permissions are required, and how quota information can be observed.
2. **Live model catalog:** exact model identifiers returned by a provider API for the current account/key at the time of the request.
3. **Model capability record:** facts about one exact model, with an explicit evidence source and confidence.

The operator catalog is useful even when live discovery is unavailable. It must not invent exact model IDs, claim every model supports a provider-level feature, or turn a curated suggestion into proof of account access.

## 2. Current implementation

- `core/providers/operator_catalog.py` contains local operator profiles for Ollama, OpenRouter, Google AI Studio, Cloudflare Workers AI, Groq, and Cohere.
- `InterfaceManager.get_provider_catalog()` combines the operator profile with any existing local model-capability manifest. It performs no network request.
- `GET /api/providers/{provider_id}/catalog` returns this local metadata.
- `GET /api/providers/{provider_id}/models` remains an explicit, bounded live discovery request through the selected adapter.
- `GET /api/providers/{provider_id}/quota` returns observed quota data only where a provider endpoint or recent inference response exposes it. Otherwise it returns an explicit unknown/not-exposed state.
- The Settings UI displays operator-level task tags, discovery scope, catalog strategy, and quota visibility separately from exact model IDs.

A successful catalog request does not prove that every returned model can be invoked. Inference failures, account permissions, model retirement, endpoint compatibility, and quotas remain separate runtime facts.

## 3. Provider discovery and quota policy

| Operator | Exact model discovery | Account / free-plan caveat | Quota visibility |
| --- | --- | --- | --- |
| Ollama | Local installed-model inventory | Only models installed on the local Ollama host are returned. | Not applicable as a hosted quota; local CPU/RAM/VRAM are host resources. |
| OpenRouter | Public `/models` catalog; the `openrouter/free` alias delegates model choice to OpenRouter. | Free variants and the router alias can be used with a normal API key; account limits still apply. | `GET /api/v1/key` exposes key usage, limit, and remaining spend when authorized. This is spend/credit telemetry, not a universal remaining-request counter. |
| Google AI Studio | Authenticated Gemini `/v1beta/models` catalog. | A free API key can list models; visible models and usable methods are project/key dependent. The Models API does not report remaining free-tier quota. | Project/model quota is not exposed as a general remaining-balance field by the model-list endpoint. |
| Cloudflare Workers AI | Account-scoped `GET /accounts/{account_id}/ai/models/search`. | Requires an API token with Workers AI Read or Workers AI Write permission. The account catalog is the source of current model IDs; free daily Neurons allowance is not a live remaining balance. | Do not infer remaining Neurons from model discovery. Use account usage/billing surfaces when an authoritative supported API is available. |
| Groq | Authenticated OpenAI-compatible `/openai/v1/models` catalog. | The list is scoped to the authenticated organization/key. Exact limits vary by model and organization. | Capture response rate-limit headers when present; the Limits dashboard is authoritative for configured organization limits. |
| Cohere | Authenticated model catalog filtered to models supporting the Chat endpoint and not marked deprecated. | Trial keys can list catalog metadata; model visibility does not guarantee that a monthly trial-call allowance remains. | Some response headers may be observed, but the monthly trial-call balance is not exposed by the model catalog. Keep it unknown. |

Provider documentation is authoritative for endpoint permissions and current policy. The application must re-check these links as providers evolve:

- [OpenRouter model catalog](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [OpenRouter current API-key usage](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)
- [OpenRouter free models and limits](https://openrouter.ai/collections/free-models)
- [Google Gemini Models API](https://ai.google.dev/api/models)
- [Google Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Cloudflare Workers AI Model Search API](https://developers.cloudflare.com/api/resources/ai/subresources/models/methods/list/)
- [Groq model catalog](https://console.groq.com/docs/models)
- [Groq rate limits and response headers](https://console.groq.com/docs/rate-limits)
- [Cohere model catalog](https://docs.cohere.com/v2/reference/list-models)
- [Cohere rate limits](https://docs.cohere.com/docs/rate-limits)
- [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)

## 4. Free accounts versus paid accounts

A paid subscription is **not universally required** to retrieve model IDs:

- OpenRouter exposes a public model catalog and a router alias. Its current-key endpoint can expose usage and remaining spend for the supplied key.
- Google AI Studio exposes a model-list API to API-key users. Free-tier model access and quotas are project-specific; the model-list endpoint does not reveal remaining quota.
- Groq and Cohere expose authenticated model-list APIs. A free/trial key can still return exact IDs, subject to account visibility and permissions.
- Cloudflare exposes account-scoped model search with Workers AI Read/Write token permission. The model list and the account's remaining free Neurons are different data.
- Ollama reports local installed models without a cloud subscription.

Therefore, do not downgrade these integrations to provider-only selections merely because the account is free. Use the operator profile for provider-level categorization and live discovery for exact IDs whenever the API permits it. If discovery is unavailable, keep the operator visible, state why discovery failed, and preserve the last selected model without presenting it as freshly verified.

## 5. Capability evidence rules

Every capability should be interpreted according to its evidence:

- `provider_declared`: provider-wide feature; not proof for every model.
- `catalog_reported`: returned in the provider's model metadata.
- `curated_manifest`: maintained locally from documentation or explicit engineering review.
- `runtime_observed`: observed from an actual request/response.
- `experimentally_verified`: tested with a controlled task and recorded result.
- `unknown`: no reliable evidence.

Provider task tags (for example, coding, analysis, translation, retrieval, or multimodal) are discovery hints. They are not model guarantees and must not be used as hard routing eligibility until a model-level record supports the requirement.

## 6. Quota and lifecycle rules

- A missing quota field is `unknown`, never zero.
- A published plan allowance is not the same as current remaining balance.
- Response headers may describe a rate window (RPM/RPD/TPM/TPD); they are not necessarily monthly account usage.
- A 401/403 indicates authentication/permission failure, not a retired model.
- A 404 or provider-specific model-not-found response may indicate a removed, renamed, or inaccessible model; retain the exact status and re-check before changing catalog lifecycle.
- A 429 indicates a rate/quota condition; capture retry/reset metadata when supplied.
- Discovery errors must not erase a user's selected model.
- Updater may propose catalog changes; only the catalog validation/approval path may update operational records. A live network response must never silently replace user settings.

## 7. Explicit non-goals

This increment does not implement persistent model history, scheduled Updater jobs, account-wide quota aggregation, encrypted credential storage, automatic task routing, or experimental capability benchmarking. These remain later milestones.
