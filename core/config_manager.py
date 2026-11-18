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


class ConfigManager:
    @staticmethod
    def _normalize(config: Dict[str, Any]) -> Dict[str, Any]:
        config.setdefault("active_provider", "ollama")
        config.setdefault("providers_config", {})
        providers = config["providers_config"]
        providers.setdefault("ollama", {})
        providers.setdefault("openrouter", {})
        providers["ollama"].setdefault("base_url", "http://localhost:11434")
        providers["openrouter"].setdefault("base_url", "https://openrouter.ai/api/v1")
        providers["openrouter"]["base_url"] = providers["openrouter"]["base_url"].rstrip("/")
        if not providers["openrouter"]["base_url"].endswith("/api/v1"):
            providers["openrouter"]["base_url"] += "/api/v1"
        providers["ollama"].setdefault("model", config.get("models", {}).get("general", ""))
        providers["openrouter"].setdefault("model", "openrouter/free")
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
        safe = copy.deepcopy(config if config is not None else ConfigManager.load_config())
        openrouter = safe.setdefault("providers_config", {}).setdefault("openrouter", {})
        openrouter["api_key_configured"] = bool(openrouter.get("api_key"))
        openrouter["api_key"] = ""
        github = safe.get("tools_config", {}).get("github", {})
        if isinstance(github, dict) and "personal_access_token" in github:
            github["personal_access_token_configured"] = bool(github.get("personal_access_token"))
            github["personal_access_token"] = ""
        return safe

    @staticmethod
    def save_config(new_config: Dict[str, Any]) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(new_config, file, ensure_ascii=False, indent=2)

    @staticmethod
    def update_config(partial_data: Dict[str, Any]) -> Dict[str, Any]:
        config = ConfigManager.load_config()
        incoming = copy.deepcopy(partial_data)
        incoming_openrouter = incoming.get("providers_config", {}).get("openrouter", {})
        if isinstance(incoming_openrouter, dict):
            incoming_openrouter.pop("api_key_configured", None)
            if not incoming_openrouter.get("api_key"):
                incoming_openrouter.pop("api_key", None)
        incoming_github = incoming.get("tools_config", {}).get("github", {})
        if isinstance(incoming_github, dict) and not incoming_github.get("personal_access_token"):
            incoming_github.pop("personal_access_token", None)
        _deep_merge(config, incoming)
        ConfigManager._normalize(config)
        if config.get("active_provider") not in ("ollama", "openrouter"):
            raise ValueError(f"Unsupported provider: {config.get('active_provider')}")
        ConfigManager.save_config(config)
        return config
