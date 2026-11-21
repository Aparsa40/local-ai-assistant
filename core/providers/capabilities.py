"""Provider/model capability catalog used by the UI and future Architect routing.

Quota figures are published plan limits; runtime telemetry is recorded only when APIs expose it.
"""

RUNTIME_QUOTA_STATUS = {}


def record_provider_quota(provider_id: str, status: dict) -> None:
    """Store non-secret rate-limit telemetry from the latest provider response."""
    RUNTIME_QUOTA_STATUS[provider_id] = dict(status)

from copy import deepcopy

PROVIDER_CATALOG = {
    "cloudflare_workers_ai": {
        "name": "Cloudflare Workers AI",
        "auth_fields": ["api_key", "account_id"],
        "streaming": True,
        "tool_calling": "model-dependent",
        "quota": {
            "plan": "Workers Free",
            "allowance": "10,000 Neurons/day",
            "reset": "00:00 UTC",
            "remaining": None,
            "status": "not_exposed_by_inference_api",
            "dashboard": "https://dash.cloudflare.com/?to=/:account/ai",
        },
        "models": {
            "@cf/zai-org/glm-4.7-flash": {
                "context_window": 131072, "tool_calling": True, "streaming": True,
                "tasks": ["general_chat", "coding", "analysis", "translation"],
                "recommended_for": ["coding", "analysis", "agent_tasks"],
                "free_tier_eligible": True,
            },
            "@cf/google/gemma-4-26b-a4b-it": {
                "context_window": None, "tool_calling": "model-dependent", "streaming": True,
                "tasks": ["general_chat", "translation", "analysis"],
                "recommended_for": ["translation", "general_chat"],
                "free_tier_eligible": True,
            },
        },
    },
    "groq": {
        "name": "Groq",
        "auth_fields": ["api_key"],
        "streaming": True,
        "tool_calling": True,
        "quota": {
            "plan": "Free developer access (organization-specific)",
            "allowance": "Per-model RPM/RPD/TPM/TPD limits shown in Groq Console",
            "remaining": None,
            "status": "unknown_until_first_api_response",
            "dashboard": "https://console.groq.com/settings/limits",
        },
        "models": {
            "openai/gpt-oss-20b": {
                "context_window": 131072, "tool_calling": True, "streaming": True,
                "tasks": ["general_chat", "coding", "analysis", "translation"],
                "recommended_for": ["general_chat", "translation"],
                "free_tier_eligible": True,
            },
            "openai/gpt-oss-120b": {
                "context_window": 131072, "tool_calling": True, "streaming": True,
                "tasks": ["coding", "analysis", "general_chat"],
                "recommended_for": ["coding", "analysis", "agent_tasks"],
                "free_tier_eligible": True,
            },
            "qwen/qwen3.8-27b": {
                "context_window": 131072, "tool_calling": True, "streaming": True,
                "tasks": ["coding", "analysis", "translation", "general_chat"],
                "recommended_for": ["coding", "analysis"],
                "free_tier_eligible": True,
            },
        },
    },
    "cohere": {
        "name": "Cohere",
        "auth_fields": ["api_key"],
        "streaming": True,
        "tool_calling": "model-dependent",
        "quota": {
            "plan": "Trial key",
            "allowance": "1,000 API calls/month; Chat: 20 requests/minute/model",
            "remaining": None,
            "status": "monthly_remaining_not_exposed",
            "dashboard": "https://dashboard.cohere.com/",
        },
        "models": {
            "command-r7b-12-2024": {
                "context_window": 128000, "tool_calling": True, "streaming": True,
                "tasks": ["general_chat", "translation", "coding"],
                "recommended_for": ["general_chat", "translation"],
                "free_tier_eligible": True,
            },
            "command-r-08-2024": {
                "context_window": 128000, "tool_calling": True, "streaming": True,
                "tasks": ["analysis", "general_chat", "translation"],
                "recommended_for": ["analysis"],
                "free_tier_eligible": True,
            },
            "command-a-03-2025": {
                "context_window": None, "tool_calling": True, "streaming": True,
                "tasks": ["coding", "analysis", "general_chat"],
                "recommended_for": ["coding", "analysis"],
                "free_tier_eligible": True,
            },
        },
    },
}


def get_provider_capabilities(provider_id: str, available_models=None) -> dict:
    """Return a defensive, JSON-safe capability manifest for a provider."""
    item = deepcopy(PROVIDER_CATALOG.get(provider_id, {}))
    if not item:
        return {}
    if provider_id in RUNTIME_QUOTA_STATUS:
        item["quota"]["runtime"] = deepcopy(RUNTIME_QUOTA_STATUS[provider_id])
    else:
        item["quota"]["runtime"] = {"status": "unknown", "message": "No recent quota telemetry available."}
    if available_models is not None:
        live = set(available_models)
        item["models"] = {
            model_id: details for model_id, details in item["models"].items()
            if model_id in live
        }
    return item
