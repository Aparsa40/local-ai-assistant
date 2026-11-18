from core.orchestrator import Orchestrator


def test_orchestrator_uses_selected_model_for_active_provider(monkeypatch):
    config = {
        "active_provider": "openrouter",
        "assistant_name": "Test assistant",
        "system_prompt": "Be helpful.",
        "providers_config": {
            "ollama": {"model": "llama3.2:1b"},
            "openrouter": {"model": "openrouter/free"},
        },
    }
    monkeypatch.setattr("core.orchestrator.ConfigManager.load_config", lambda: config)
    orchestrator = Orchestrator()

    messages, model = orchestrator.build_messages([], "Hello")

    assert model == "openrouter/free"
    assert messages[-1] == {"role": "user", "content": "Hello"}


def test_ollama_and_openrouter_model_choices_are_independent(monkeypatch):
    config = {
        "active_provider": "ollama",
        "assistant_name": "Test",
        "system_prompt": "Test",
        "providers_config": {
            "ollama": {"model": "qwen2.5-coder:0.5b"},
            "openrouter": {"model": "openrouter/free"},
        },
    }
    monkeypatch.setattr("core.orchestrator.ConfigManager.load_config", lambda: config)
    orchestrator = Orchestrator()
    assert orchestrator.select_model() == "qwen2.5-coder:0.5b"
    config["active_provider"] = "openrouter"
    assert orchestrator.select_model() == "openrouter/free"
