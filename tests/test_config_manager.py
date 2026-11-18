import json

from core.config_manager import ConfigManager


def test_legacy_settings_are_migrated_and_openrouter_defaults_to_free_router(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.json"
    example_path = tmp_path / "settings.example.json"
    config_path.write_text(json.dumps({
        "assistant_name": "Test",
        "models": {"general": "llama3.2:1b"},
        "providers_config": {"openrouter": {"api_key": "secret", "base_url": "https://openrouter.ai"}},
    }), encoding="utf-8")
    monkeypatch.setattr("core.config_manager.CONFIG_PATH", config_path)
    monkeypatch.setattr("core.config_manager.EXAMPLE_CONFIG_PATH", example_path)

    config = ConfigManager.load_config()

    assert config["providers_config"]["ollama"]["model"] == "llama3.2:1b"
    assert config["providers_config"]["openrouter"]["model"] == "openrouter/free"
    assert config["providers_config"]["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert ConfigManager.public_config(config)["providers_config"]["openrouter"]["api_key"] == ""
    assert ConfigManager.public_config(config)["providers_config"]["openrouter"]["api_key_configured"] is True


def test_empty_api_key_update_preserves_existing_secret(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.json"
    example_path = tmp_path / "settings.example.json"
    config_path.write_text(json.dumps({
        "active_provider": "openrouter",
        "providers_config": {"openrouter": {"api_key": "keep-this", "model": "openrouter/free"}},
    }), encoding="utf-8")
    monkeypatch.setattr("core.config_manager.CONFIG_PATH", config_path)
    monkeypatch.setattr("core.config_manager.EXAMPLE_CONFIG_PATH", example_path)

    ConfigManager.update_config({
        "providers_config": {"openrouter": {"api_key": "", "model": "openrouter/free"}}
    })

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers_config"]["openrouter"]["api_key"] == "keep-this"
