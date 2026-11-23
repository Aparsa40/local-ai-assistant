import copy
import json
import shutil
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path("config/settings.json")
EXAMPLE_CONFIG_PATH = Path("config/settings.example.json")


def _deep_merge(target: dict, updates: dict) -> dict:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


_SECRET_KEY_MARKERS = (
    "api_key", "access_token", "refresh_token", "personal_access_token",
    "secret", "password", "credential", "authorization", "private_key",
)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    generic_token_fields = {"token", "api_token", "auth_token", "client_token", "id_token"}
    return (
        normalized in generic_token_fields
        or (normalized.endswith("_token") and not normalized.endswith("_tokens"))
        or any(marker in normalized for marker in _SECRET_KEY_MARKERS)
    )


def _redact_secrets(value: Any) -> Any:
    """Recursively redact credential-like fields in provider and tool settings."""
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            if str(key).endswith("_configured"):
                safe[key] = item
            elif _is_secret_key(str(key)):
                safe[f"{key}_configured"] = bool(item)
                safe[key] = ""
            else:
                safe[key] = _redact_secrets(item)
        return safe
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _remove_empty_secret_updates(incoming: Any, existing: Any) -> None:
    """Remove blank secret updates so an omitted/empty UI field keeps its old value."""
    if not isinstance(incoming, dict) or not isinstance(existing, dict):
        return
    for key in list(incoming):
        value = incoming[key]
        if key.endswith("_configured"):
            incoming.pop(key)
            continue
        if _is_secret_key(str(key)) and value in (None, ""):
            incoming.pop(key)
            continue
        if isinstance(value, dict):
            _remove_empty_secret_updates(value, existing.get(key, {}))


class ConfigManager:
    @staticmethod
    def _normalize(config: Dict[str, Any]) -> Dict[str, Any]:
        # Migrate legacy installations once, preserving all supported explicit selections.
        schema_version = int(config.get("settings_schema_version", 0) or 0)
        if schema_version < 2:
            if config.get("active_provider") in (None, "ollama"):
                config["active_provider"] = "openrouter"
            schema_version = 2
        if schema_version < 3:
            # Hugging Face is intentionally retired. Keep the user's app usable by
            # switching only the retired active provider to the known free router.
            if config.get("active_provider") == "huggingface":
                config["active_provider"] = "openrouter"
            config.setdefault("providers_config", {}).pop("huggingface", None)
            schema_version = 3
        config["settings_schema_version"] = schema_version
        config.setdefault("active_provider", "openrouter")
        config.setdefault("providers_config", {})
        providers = config["providers_config"]
        for provider_id in (
            "ollama", "openrouter", "google_ai_studio",
            "cloudflare_workers_ai", "groq", "cohere",
        ):
            providers.setdefault(provider_id, {})
        providers["ollama"].setdefault("base_url", "http://localhost:11434")
        providers["ollama"].setdefault("auto_start", True)
        providers["ollama"].setdefault("model", config.get("models", {}).get("general", ""))
        providers["openrouter"].setdefault("base_url", "https://openrouter.ai/api/v1")
        providers["openrouter"]["base_url"] = providers["openrouter"]["base_url"].rstrip("/")
        if not providers["openrouter"]["base_url"].endswith("/api/v1"):
            providers["openrouter"]["base_url"] += "/api/v1"
        providers["openrouter"].setdefault("model", "openrouter/free")
        providers["google_ai_studio"].setdefault(
            "base_url", "https://generativelanguage.googleapis.com/v1beta"
        )
        providers["google_ai_studio"].setdefault("model", "gemini-3.8-flash")
        providers["cloudflare_workers_ai"].setdefault(
            "base_url", "https://api.cloudflare.com/client/v4"
        )
        providers["cloudflare_workers_ai"].setdefault("account_id", "")
        if not providers["cloudflare_workers_ai"].get("model"):
            providers["cloudflare_workers_ai"]["model"] = "@cf/zai-org/glm-4.7-flash"
        providers["groq"].setdefault("base_url", "https://api.groq.com/openai/v1")
        if not providers["groq"].get("model"):
            providers["groq"]["model"] = "openai/gpt-oss-20b"
        providers["cohere"].setdefault("base_url", "https://api.cohere.com")
        if not providers["cohere"].get("model"):
            providers["cohere"]["model"] = "command-r7b-12-2024"
        config.setdefault("routing_mode", "manual")
        config.setdefault("assistant_name", "Local AI Assistant")
        config.setdefault("system_prompt", "You are a helpful assistant.")
        return config

    @staticmethod
    def load_config() -> Dict[str, Any]:
        if not CONFIG_PATH.exists():
            if not EXAMPLE_CONFIG_PATH.exists():
                raise FileNotFoundError("Neither config/settings.json nor config/settings.example.json exists.")
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
        normalized = ConfigManager._normalize(config)
        if normalized != config:
            ConfigManager.save_config(normalized)
        return normalized

    @staticmethod
    def public_config(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        source = config if config is not None else ConfigManager.load_config()
        return _redact_secrets(copy.deepcopy(source))

    @staticmethod
    def save_config(new_config: Dict[str, Any]) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(new_config, file, ensure_ascii=False, indent=2)

    @staticmethod
    def update_config(partial_data: Dict[str, Any]) -> Dict[str, Any]:
        config = ConfigManager.load_config()
        incoming = copy.deepcopy(partial_data)
        _remove_empty_secret_updates(incoming, config)
        _deep_merge(config, incoming)
        ConfigManager._normalize(config)
        active_provider = config.get("active_provider")
        from core.providers.registry import PROVIDER_FACTORIES
        if active_provider not in PROVIDER_FACTORIES:
            raise ValueError(f"Unsupported provider: {active_provider}")
        ConfigManager.save_config(config)
        return config
