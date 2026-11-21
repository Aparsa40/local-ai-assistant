# Cloud Provider Capability Notes

**Scope:** This is a focused operational reference for selected cloud-provider capability and quota metadata. It is not the complete provider inventory and does not replace [PROVIDER_SYSTEM.md](PROVIDER_SYSTEM.md) or [MODEL_MANAGER.md](MODEL_MANAGER.md).

The current repository also includes adapters for Ollama, OpenRouter, and Google AI Studio/Gemini. The cloud-provider details below focus on Cloudflare Workers AI, Groq, and Cohere because those entries have additional curated capability/quota notes.

Provider quotas and model catalogs change. Treat recommendations and free-tier metadata as time-sensitive operational data, not permanent guarantees.

## Provider overview

| Provider | Authentication | Streaming | Tool calling | Free allowance / quota visibility |
| --- | --- | --- | --- | --- |
| Cloudflare Workers AI | API token + Account ID | SSE | Model-dependent | Workers Free allowance is plan-level; remaining Neurons may be unknown in-app when the inference endpoint does not expose a live balance. |
| Groq | API key | SSE | Supported models expose function/tool calling | Organization- and model-specific limits; consult the Groq Console and response headers. |
| Cohere | Trial API key | SSE | Model-dependent | Trial quotas are subject to change; monthly remaining calls may not be exposed by the model-list endpoint. |

## Curated model notes

The following entries are historical/curated recommendations and must be re-verified against live provider documentation and account availability before being treated as current recommendations.

| Provider / Model | Context window | Recommended tasks | Tool calling |
| --- | ---: | --- | --- |
| Cloudflare `@cf/zai-org/glm-4.7-flash` | 131,072 (verify before use) | Coding, analysis, multilingual chat, agent tasks | Yes (verify model support) |
| Cloudflare `@cf/google/gemma-4-26b-a4b-it` | Not asserted | Translation, general chat | Model-dependent |
| Groq `openai/gpt-oss-20b` | 131,072 (verify before use) | Everyday chat, translation, lightweight coding | Yes |
| Groq `openai/gpt-oss-120b` | 131,072 (verify before use) | Coding, deeper analysis, agent tasks | Yes |
| Groq `qwen/qwen3.8-27b` | 131,072 (verify before use) | Coding, analysis, multilingual requests | Yes |
| Cohere `command-r7b-12-2024` | 128,000 (verify before use) | General chat, translation, lightweight coding | Yes |
| Cohere `command-r-08-2024` | 128,000 (verify before use) | Analysis, retrieval-oriented conversation | Yes |
| Cohere `command-a-03-2025` | Read live model metadata | Coding and analysis | Verify live model support |

## Runtime notes

- Provider IDs are stable machine identifiers.
- Exact provider model IDs must be preserved.
- Provider-level support does not prove every model supports a capability.
- A published plan allowance is not a live remaining balance.
- Unknown quota must remain `unknown`; it must not be treated as exhausted or unlimited.
- Model IDs, context limits, tool support, pricing, and free-tier eligibility must be re-checked before updating curated recommendations.
- Capability entries should include evidence class and last-verified timestamp when implemented.

## Routing implications

The current chat flow remains manual provider/model selection. Capability metadata is groundwork for future routing, not proof that automatic routing is active.

Potential task labels include `general_chat`, `coding`, `analysis`, `translation`, and `agent_tasks`. Future routing must also consider context limits, modalities, tool requirements, credentials, provider health, and quota state.

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
