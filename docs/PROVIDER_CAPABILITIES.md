# Cloud Provider Capability Matrix

This document records the provider contracts and the currently curated model recommendations. Provider quotas and model catalogs can change; the runtime catalog is refreshed from each provider where the API supports discovery.

## Provider overview

| Provider | Authentication | Streaming | Tool calling | Free allowance / quota visibility |
| --- | --- | --- | --- | --- |
| Cloudflare Workers AI | API token + Account ID | SSE | Model-dependent | Workers Free includes 10,000 Neurons/day; the inference endpoint does not expose remaining daily Neurons, so remaining quota is unknown in-app. |
| Groq | API key | SSE | Supported models expose function/tool calling | Organization- and model-specific RPM/RPD/TPM/TPD; exact limits are shown in the Groq Console and response headers. |
| Cohere | Trial API key | SSE | Model-dependent | Trial keys: 1,000 API calls/month; Chat models: 20 requests/minute/model. Monthly remaining calls are not exposed by the model-list endpoint. |

## Recommended model assignments

| Provider / Model | Context window | Recommended tasks | Tool calling |
| --- | ---: | --- | --- |
| Cloudflare `@cf/zai-org/glm-4.7-flash` | 131,072 | Coding, analysis, multilingual chat, agent tasks | Yes |
| Cloudflare `@cf/google/gemma-4-26b-a4b-it` | Not asserted until verified from live model metadata | Translation, general chat | Model-dependent |
| Groq `openai/gpt-oss-20b` | 131,072 | Everyday chat, translation, lightweight coding | Yes |
| Groq `openai/gpt-oss-120b` | 131,072 | Coding, deeper analysis, agent tasks | Yes |
| Groq `qwen/qwen3.8-27b` | 131,072 | Coding, analysis, multilingual requests | Yes |
| Cohere `command-r7b-12-2024` | 128,000 | General chat, translation, lightweight coding | Yes |
| Cohere `command-r-08-2024` | 128,000 | Analysis, retrieval-oriented conversation | Yes |
| Cohere `command-a-03-2025` | Read live model metadata | Coding and analysis | Yes |

## Runtime contract

- Provider IDs are stable machine identifiers: `cloudflare_workers_ai`, `groq`, and `cohere`.
- Provider credentials stay in the ignored local `config/settings.json`. The settings API recursively redacts secrets; blank form submissions preserve existing values.
- Cloudflare requires both `api_key` and `account_id`.
- The model endpoint returns exact provider model IDs. The capability endpoint returns context length, supported tasks, streaming, tool-calling, free-tier eligibility, quota policy, and a quota-status field.
- A published plan allowance is not the same as a live remaining balance. The UI and future Architect must show `unknown` rather than inventing a remaining quota when the provider does not expose it.
- Model IDs and free-tier eligibility are versioned operational data, not permanent guarantees. Re-check provider catalogs and pricing pages before updating the curated allowlists.

## Architect routing contract

The current chat flow remains manual provider/model selection. The metadata is groundwork for a future Architect, not a claim that automatic routing is already active.

Suggested task labels:

- `general_chat`
- `coding`
- `analysis`
- `translation`
- `agent_tasks`

The future router should filter models by task capability, context-window requirement, tool-call requirement, configured credentials, and quota/health state before scoring latency and quality. If quota state is unknown, it must not treat the provider as either exhausted or fully available.

## Official references

- Cloudflare Workers AI pricing: https://developers.cloudflare.com/workers-ai/platform/pricing/
- Cloudflare Workers AI limits: https://developers.cloudflare.com/workers-ai/platform/limits/
- Cloudflare model catalog: https://developers.cloudflare.com/workers-ai/models/
- Groq supported models: https://console.groq.com/docs/models
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq tool use: https://console.groq.com/docs/tool-use/overview
- Cohere rate limits: https://docs.cohere.com/docs/rate-limits
- Cohere model catalog: https://docs.cohere.com/v2/reference/list-models
- Cohere streaming Chat API: https://docs.cohere.com/v2/reference/chat-stream
