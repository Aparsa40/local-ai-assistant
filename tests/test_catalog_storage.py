import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.catalog_storage import (
    get_provider_catalog_snapshot,
    record_provider_runtime,
    record_sync_failure,
    save_intelligence_report,
    seed_operator_catalogs,
    sync_live_models,
)
from core.database import Base, LiveModelCatalogEntry, OperatorModelProfile, ProviderIntelligenceReport, to_utc_naive, utcnow_naive


class CatalogStorageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_utc_timestamp_helpers_preserve_naive_utc_storage_contract(self):
        now = utcnow_naive()
        self.assertIsNone(now.tzinfo)

        offset_timestamp = datetime(2026, 11, 22, 12, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(
            to_utc_naive(offset_timestamp),
            datetime(2026, 11, 22, 9, 0),
        )

        legacy_naive_timestamp = datetime(2026, 11, 22, 9, 0)
        self.assertIs(to_utc_naive(legacy_naive_timestamp), legacy_naive_timestamp)

    def test_provider_runtime_timestamp_is_normalized_to_utc_before_storage(self):
        record_provider_runtime(
            self.db,
            "groq",
            {
                "status": "reachable",
                "checked_at": "2026-11-22T12:00:00+03:00",
            },
        )
        snapshot = get_provider_catalog_snapshot(self.db, "groq")
        self.assertEqual(snapshot["provider_runtime"]["checked_at"], "2026-11-22T09:00:00")

    def test_operator_manifests_and_curated_profiles_are_seeded(self):
        count = seed_operator_catalogs(self.db)
        self.assertEqual(count, 6)
        snapshot = get_provider_catalog_snapshot(self.db, "groq")
        self.assertEqual(snapshot["operator"]["name"], "Groq")
        self.assertTrue(snapshot["curated_models"])
        self.assertEqual(snapshot["live_models"], [])

    def test_seed_retires_profiles_removed_from_current_manifest(self):
        seed_operator_catalogs(self.db)

        stale_model_id = "__retired_manifest_model__"
        self.db.add(OperatorModelProfile(
            provider_id="groq",
            model_id=stale_model_id,
            profile={"tasks": ["chat"]},
        ))
        self.db.add(LiveModelCatalogEntry(
            provider_id="groq",
            model_id=stale_model_id,
            catalog_data={},
            source="provider_api",
            active=True,
        ))
        self.db.commit()

        seed_operator_catalogs(self.db)

        self.assertIsNone(self.db.get(OperatorModelProfile, ("groq", stale_model_id)))
        snapshot = get_provider_catalog_snapshot(self.db, "groq")
        live_model = next(
            row for row in snapshot["live_models"]
            if row["model_id"] == stale_model_id
        )
        self.assertIsNone(live_model["operator_profile"])
        self.assertTrue(snapshot["curated_models"])

    def test_live_catalog_is_provider_scoped_and_tracks_retired_models(self):
        first = sync_live_models(self.db, "groq", ["model-a", "model-b"])
        self.assertEqual(first["added_count"], 2)
        second = sync_live_models(self.db, "groq", ["model-b", "model-c"])
        self.assertEqual(second["added_count"], 1)
        self.assertEqual(second["retired_count"], 1)

        groq = get_provider_catalog_snapshot(self.db, "groq")
        models = {row["model_id"]: row for row in groq["live_models"]}
        self.assertFalse(models["model-a"]["active"])
        self.assertTrue(models["model-b"]["active"])
        self.assertTrue(models["model-c"]["active"])

        sync_live_models(self.db, "cohere", ["model-a"])
        cohere = get_provider_catalog_snapshot(self.db, "cohere")
        self.assertEqual([row["model_id"] for row in cohere["live_models"]], ["model-a"])
        self.assertEqual(
            self.db.query(LiveModelCatalogEntry).filter_by(provider_id="groq", model_id="model-a").count(),
            1,
        )

    def test_empty_discovery_preserves_existing_active_catalog(self):
        sync_live_models(self.db, "groq", ["model-a"])
        result = sync_live_models(self.db, "groq", [])
        self.assertEqual(result["status"], "empty_response_preserved")
        snapshot = get_provider_catalog_snapshot(self.db, "groq")
        self.assertTrue(snapshot["live_models"][0]["active"])

    def test_failed_sync_does_not_clear_last_known_good_catalog(self):
        sync_live_models(self.db, "groq", ["model-a", "model-b"])
        record_sync_failure(self.db, "groq", {"category": "timeout", "message": "Timed out"})
        snapshot = get_provider_catalog_snapshot(self.db, "groq")
        active_ids = {row["model_id"] for row in snapshot["live_models"] if row["active"]}
        self.assertEqual(active_ids, {"model-a", "model-b"})
        self.assertEqual(snapshot["sync_history"][0]["status"], "failed")


    def test_live_model_metadata_is_persisted_and_updated(self):
        sync_live_models(
            self.db,
            "ollama",
            ["llama3.2:1b"],
            model_metadata={"llama3.2:1b": {"size": 123, "capabilities": ["completion"]}},
        )
        first = get_provider_catalog_snapshot(self.db, "ollama")
        self.assertEqual(first["live_models"][0]["catalog_data"]["size"], 123)

        sync_live_models(
            self.db,
            "ollama",
            ["llama3.2:1b"],
            model_metadata={"llama3.2:1b": {"size": 456, "capabilities": ["tools"]}},
        )
        updated = get_provider_catalog_snapshot(self.db, "ollama")
        self.assertEqual(updated["live_models"][0]["catalog_data"]["size"], 456)
        self.assertEqual(updated["live_models"][0]["catalog_data"]["capabilities"], ["tools"])

        sync_live_models(
            self.db,
            "ollama",
            ["llama3.2:1b"],
            model_metadata={"llama3.2:1b": {"size": 789, "details": {"family": "llama"}}},
        )
        partial = get_provider_catalog_snapshot(self.db, "ollama")
        self.assertEqual(partial["live_models"][0]["catalog_data"]["capabilities"], ["tools"])

    def test_intelligence_report_history_is_bounded_per_provider_and_type(self):
        for index in range(3):
            generated = utcnow_naive().isoformat()
            save_intelligence_report(
                self.db,
                {
                    "provider_id": "ollama",
                    "report_type": "runtime",
                    "generated_at": generated,
                    "source_snapshot_at": generated,
                    "overall_status": "healthy",
                    "summary": f"report-{index}",
                    "models": [],
                },
                history_limit=2,
            )

        self.assertEqual(
            self.db.query(ProviderIntelligenceReport).filter_by(
                provider_id="ollama", report_type="runtime"
            ).count(),
            2,
        )


    def test_provider_runtime_persists_local_process_ownership_details(self):
        record_provider_runtime(
            self.db,
            "ollama",
            {
                "status": "reachable",
                "checked_at": utcnow_naive().isoformat(),
                "runtime": {
                    "started_by_application": True,
                    "process_id": 12345,
                    "endpoint_scope": "local",
                },
            },
        )
        snapshot = get_provider_catalog_snapshot(self.db, "ollama")
        self.assertTrue(snapshot["provider_runtime"]["runtime_details"]["started_by_application"])
        self.assertEqual(snapshot["provider_runtime"]["runtime_details"]["process_id"], 12345)


def test_init_db_migrates_existing_provider_runtime_status_table(tmp_path, monkeypatch):
    from core import database as database_module

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE provider_runtime_status ("
            "provider_id VARCHAR(80) PRIMARY KEY, "
            "status VARCHAR(40) NOT NULL, "
            "probe VARCHAR(80), "
            "model_count INTEGER, "
            "checked_at DATETIME, "
            "error JSON, "
            "updated_at DATETIME NOT NULL)"
        ))

    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_PATH", tmp_path / "chat_history.db")
    try:
        database_module.init_db()
        columns = {column["name"] for column in inspect(engine).get_columns("provider_runtime_status")}
        assert "runtime_details" in columns
    finally:
        engine.dispose()

def test_unchanged_intelligence_report_is_not_persisted_twice():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        first = {
            "provider_id": "ollama",
            "report_type": "runtime",
            "generated_at": utcnow_naive().isoformat(),
            "source_snapshot_at": utcnow_naive().isoformat(),
            "overall_status": "healthy",
            "summary": "same semantic report",
            "fingerprint": "stable-fingerprint",
            "models": [],
        }
        saved = save_intelligence_report(session, first)
        duplicate = dict(first, generated_at=(utcnow_naive() + timedelta(seconds=1)).isoformat())

        result = save_intelligence_report(session, duplicate)

        assert saved["saved"] is True
        assert result["saved"] is False
        assert result["reason"] == "unchanged"
        assert session.query(ProviderIntelligenceReport).filter_by(
            provider_id="ollama", report_type="runtime"
        ).count() == 1
    finally:
        session.close()
        engine.dispose()

if __name__ == "__main__":
    unittest.main()
