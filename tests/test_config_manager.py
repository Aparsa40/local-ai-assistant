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


def test_custom_provider_secret_is_redacted_and_blank_update_is_preserved(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.json"
    example_path = tmp_path / "settings.example.json"
    config_path.write_text(json.dumps({
        "active_provider": "custom-cloud",
        "providers_config": {
            "custom-cloud": {
                "api_key": "custom-secret",
                "nested": {"access_token": "nested-secret"},
                "model": "custom-model",
            }
        },
    }), encoding="utf-8")
    monkeypatch.setattr("core.config_manager.CONFIG_PATH", config_path)
    monkeypatch.setattr("core.config_manager.EXAMPLE_CONFIG_PATH", example_path)

    from core.providers.registry import PROVIDER_FACTORIES
    monkeypatch.setitem(PROVIDER_FACTORIES, "custom-cloud", lambda config: object())

    public = ConfigManager.public_config()
    custom = public["providers_config"]["custom-cloud"]
    assert custom["api_key"] == ""
    assert custom["api_key_configured"] is True
    assert custom["nested"]["access_token"] == ""
    assert custom["nested"]["access_token_configured"] is True

    ConfigManager.update_config({
        "active_provider": "custom-cloud",
        "providers_config": {
            "custom-cloud": {
                "api_key": "",
                "nested": {"access_token": ""},
                "model": "updated-model",
            }
        },
    })
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    custom_saved = saved["providers_config"]["custom-cloud"]
    assert custom_saved["api_key"] == "custom-secret"
    assert custom_saved["nested"]["access_token"] == "nested-secret"
    assert custom_saved["model"] == "updated-model"


def test_unregistered_provider_cannot_be_activated(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.json"
    example_path = tmp_path / "settings.example.json"
    config_path.write_text(json.dumps({
        "active_provider": "ollama",
        "providers_config": {"ollama": {"model": "llama3.2:1b"}},
    }), encoding="utf-8")
    monkeypatch.setattr("core.config_manager.CONFIG_PATH", config_path)
    monkeypatch.setattr("core.config_manager.EXAMPLE_CONFIG_PATH", example_path)

    try:
        ConfigManager.update_config({"active_provider": "not-registered"})
    except ValueError as exc:
        assert "Unsupported provider" in str(exc)
    else:
        raise AssertionError("An unregistered provider must not be activated")
