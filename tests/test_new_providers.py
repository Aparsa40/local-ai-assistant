from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import asyncio

import pytest

from core.providers.google_ai_studio_provider import FREE_TIER_MODEL_IDS, GoogleAIStudioProvider
from core.providers.cloudflare_provider import CloudflareWorkersAIProvider
from core.providers.cohere_provider import CohereProvider
from core.providers.groq_provider import GroqProvider
from core.providers.capabilities import get_provider_capabilities


def test_gemini_interactions_text_delta_and_free_models():
    event = {"event_type": "step.delta", "delta": {"type": "text", "text": "سلام"}}
    assert GoogleAIStudioProvider._extract_stream_content(event) == "سلام"
    assert "gemini-2.5-flash" in FREE_TIER_MODEL_IDS


def test_cloudflare_stream_response_extraction():
    assert CloudflareWorkersAIProvider._extract_text({"response": "سلام"}) == "سلام"
    assert CloudflareWorkersAIProvider._extract_text({"result": {"response": "Hello"}}) == "Hello"


def test_cloudflare_requires_account_and_token():
    provider = CloudflareWorkersAIProvider(api_key="", account_id="")
    with pytest.raises(RuntimeError, match="token is missing"):
        provider._headers()
    provider = CloudflareWorkersAIProvider(api_key="token", account_id="")
    with pytest.raises(RuntimeError, match="Account ID is missing"):
        provider._headers()


def test_cohere_content_delta_extraction():
    event = {
        "type": "content-delta",
        "delta": {"message": {"content": {"text": "سلام"}}},
    }
    assert CohereProvider._extract_text(event) == "سلام"


def test_cohere_ignores_non_text_events():
    assert CohereProvider._extract_text({"type": "message-start"}) == ""


def test_groq_recommended_models_are_current_and_task_suitable():
    from core.providers.groq_provider import RECOMMENDED_MODELS
    assert "openai/gpt-oss-20b" in RECOMMENDED_MODELS
    assert "openai/gpt-oss-120b" in RECOMMENDED_MODELS
    assert "qwen/qwen3.8-27b" in RECOMMENDED_MODELS


def test_provider_capabilities_include_quota_and_model_metadata():
    data = get_provider_capabilities("cloudflare_workers_ai")
    assert data["quota"]["allowance"] == "10,000 Neurons/day"
    assert data["models"]["@cf/zai-org/glm-4.7-flash"]["context_window"] == 131072
    assert data["models"]["@cf/zai-org/glm-4.7-flash"]["tool_calling"] is True


def test_capability_catalog_filters_to_live_discovered_models():
    data = get_provider_capabilities("groq", ["openai/gpt-oss-20b"])
    assert list(data["models"]) == ["openai/gpt-oss-20b"]



def test_capability_and_operator_catalog_endpoints_do_not_trigger_remote_discovery(monkeypatch):
    import main

    async def unexpected_discovery(_provider_id):
        raise AssertionError("Local metadata endpoints must not call remote model discovery")

    monkeypatch.setattr(main.interface_manager, "list_models", unexpected_discovery)
    capabilities = asyncio.run(main.provider_capabilities("groq"))
    operator_catalog = asyncio.run(main.provider_catalog("groq"))

    assert "openai/gpt-oss-20b" in capabilities["models"]
    assert capabilities["quota"]["runtime"]["status"] == "unknown"
    assert operator_catalog["operator"]["catalog_mode"] == "live_authenticated_catalog"
    assert operator_catalog["catalog_source"] == "local_operator_manifest"


def test_connection_probe_rejects_get_and_remains_post_only():
    import main

    response = TestClient(main.app).get("/api/providers/groq/connection")

    assert response.status_code == 405
    assert "POST" in response.headers.get("allow", "")
    assert "GET" not in response.headers.get("allow", "")


def test_offline_intelligence_report_api_reads_and_persists_sqlite_snapshot():
    import main
    from core.catalog_storage import seed_operator_catalogs
    from core.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    seed_operator_catalogs(db)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        client = TestClient(main.app)
        response = client.post("/api/intelligence/reports/offline?provider_id=groq")
        assert response.status_code == 200
        assert response.json()["report_type"] == "offline"

        latest = client.get("/api/intelligence/reports/latest?provider_id=groq&report_type=offline")
        assert latest.status_code == 200
        assert latest.json()["provider_id"] == "groq"
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        db.close()
        engine.dispose()
