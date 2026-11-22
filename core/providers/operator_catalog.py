"""Operator-level catalog metadata.

This catalog describes provider/operator behavior, discovery support and quota
visibility. It deliberately does not invent model IDs or claim that every model
inherits every provider-level capability. Exact model IDs remain sourced from
provider discovery or explicitly curated model manifests.
"""
from copy import deepcopy


OPERATOR_CATALOG = {
    "ollama": {
        "name": "Ollama",
        "category": "local_runtime",
        "catalog_mode": "live_local_inventory",
        "discovery": {"available": True, "scope": "installed_local_models", "requires_credentials": False},
        "model_selection": "exact_model_id",
        "task_tags": ["local_inference", "privacy_sensitive", "general_chat", "coding", "analysis"],
        "quota": {"visibility": "not_applicable", "live_remaining": False, "notes": "Local resource limits depend on the host machine."},
        "evidence": "runtime_inventory",
        "source_url": "https://github.com/ollama/ollama/blob/main/docs/api.md",
    },
    "openrouter": {
        "name": "OpenRouter",
        "category": "cloud_model_router",
        "catalog_mode": "live_catalog_and_router_alias",
        "discovery": {"available": True, "scope": "public_catalog_with_free_pricing_filter", "requires_credentials": False},
        "model_selection": "exact_model_id_or_router_alias",
        "router_aliases": ["openrouter/free"],
        "task_tags": ["general_chat", "analysis", "coding", "translation", "multimodal"],
        "quota": {"visibility": "key_api", "live_remaining": True, "endpoint": "GET /api/v1/key", "notes": "Key usage and remaining spend are available when the key endpoint authorizes the supplied key; free-model request caps remain separate."},
        "evidence": "provider_catalog_and_key_telemetry",
        "source_url": "https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key",
    },
    "google_ai_studio": {
        "name": "Google AI Studio",
        "category": "cloud_model_provider",
        "catalog_mode": "live_authenticated_catalog",
        "discovery": {"available": True, "scope": "models_visible_to_api_key", "requires_credentials": True},
        "model_selection": "exact_model_id",
        "task_tags": ["general_chat", "reasoning", "coding", "analysis", "multimodal", "translation"],
        "quota": {"visibility": "project_and_model_specific", "live_remaining": False, "notes": "The Models API lists models and supported actions; it does not expose the project's remaining free-tier quota. Limits and access depend on project and model."},
        "evidence": "provider_catalog_plus_published_pricing",
        "source_url": "https://ai.google.dev/api/models",
    },
    "cloudflare_workers_ai": {
        "name": "Cloudflare Workers AI",
        "category": "cloud_model_provider",
        "catalog_mode": "account_scoped_live_catalog",
        "discovery": {"available": True, "scope": "account_catalog", "requires_credentials": True, "required_permission": "Workers AI Read or Workers AI Write"},
        "model_selection": "exact_model_id",
        "task_tags": ["general_chat", "coding", "analysis", "translation", "embeddings", "speech", "multimodal"],
        "quota": {"visibility": "plan_allowance_and_usage_dashboard", "live_remaining": False, "notes": "The model-search endpoint is account-scoped. A published daily allowance is not the same as a live remaining balance; do not infer remaining Neurons from model discovery."},
        "evidence": "account_catalog_and_published_plan",
        "source_url": "https://developers.cloudflare.com/api/resources/ai/subresources/models/methods/list/",
    },
    "groq": {
        "name": "Groq",
        "category": "cloud_inference_provider",
        "catalog_mode": "live_authenticated_catalog",
        "discovery": {"available": True, "scope": "models_visible_to_api_key", "requires_credentials": True},
        "model_selection": "exact_model_id",
        "task_tags": ["low_latency_inference", "general_chat", "coding", "analysis", "translation", "speech"],
        "quota": {"visibility": "response_rate_limit_headers_and_account_dashboard", "live_remaining": True, "notes": "Capture provider response headers for remaining requests/tokens and reset windows. Exact organization limits are account-specific; the dashboard remains authoritative."},
        "evidence": "provider_catalog_and_response_headers",
        "source_url": "https://console.groq.com/docs/rate-limits",
    },
    "cohere": {
        "name": "Cohere",
        "category": "cloud_inference_provider",
        "catalog_mode": "live_authenticated_catalog",
        "discovery": {"available": True, "scope": "chat_endpoint_compatible_models", "requires_credentials": True},
        "model_selection": "exact_model_id",
        "task_tags": ["general_chat", "retrieval", "reranking", "embeddings", "analysis", "translation"],
        "quota": {"visibility": "published_trial_limits_and_partial_response_headers", "live_remaining": False, "notes": "The model catalog exposes model/endpoint metadata, not the monthly trial-call balance. Preserve monthly remaining as unknown unless Cohere exposes an authoritative usage endpoint."},
        "evidence": "provider_catalog_and_published_trial_policy",
        "source_url": "https://docs.cohere.com/docs/rate-limits",
    },
}


def get_operator_catalog(provider_id: str) -> dict:
    """Return a defensive copy of one operator profile."""
    item = OPERATOR_CATALOG.get(provider_id)
    return deepcopy(item) if item else {}


def list_operator_catalogs() -> dict:
    """Return defensive copies of all operator profiles keyed by stable ID."""
    return deepcopy(OPERATOR_CATALOG)
