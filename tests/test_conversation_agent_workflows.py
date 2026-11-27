from contextlib import contextmanager

import pytest

from core.conversation_agent.workflows import WorkflowRegistry, build_default_workflow_registry


def test_registry_rejects_duplicate_and_unknown_workflows():
    registry = WorkflowRegistry()
    registry.register("sample_report", "Sample", lambda: "ok")
    with pytest.raises(ValueError):
        registry.register("sample_report", "Duplicate", lambda: "other")
    with pytest.raises(LookupError):
        registry.execute("not_registered")


def test_registry_rejects_invalid_names_and_empty_results():
    registry = WorkflowRegistry()
    with pytest.raises(ValueError):
        registry.register("../unsafe", "Unsafe", lambda: "no")
    registry.register("empty_result", "Empty", lambda: "  ")
    with pytest.raises(ValueError):
        registry.execute("empty_result")


def test_default_provider_report_uses_existing_operational_catalog_service(monkeypatch):
    from core import catalog_storage

    seen = []

    @contextmanager
    def session_factory():
        token = object()
        seen.append(token)
        yield token

    def fake_report(db):
        assert db is seen[0]
        return {
            "generated_at": "2026-11-28T00:00:00",
            "providers": [
                {
                    "provider_id": "ollama",
                    "operator": {"name": "Ollama"},
                    "provider_runtime": {"status": "ready"},
                    "live_models": [
                        {"model_id": "qwen2.5:0.5b", "active": True},
                        {"model_id": "old-model", "active": False},
                    ],
                }
            ],
        }

    monkeypatch.setattr(catalog_storage, "get_operational_report", fake_report)
    registry = build_default_workflow_registry(session_factory)

    assert registry.names() == ("provider_operational_report",)
    result = registry.execute("provider_operational_report")
    assert "تعداد Providerهای ثبت‌شده: 1" in result
    assert "Ollama: وضعیت Runtime=ready، مدل‌های فعال=1 از 2" in result
    assert "Probe زنده اجرا نمی‌کند" in result
    assert len(seen) == 1
