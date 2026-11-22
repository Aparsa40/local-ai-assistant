import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.catalog_storage import (
    get_provider_catalog_snapshot,
    record_provider_runtime,
    record_sync_failure,
    seed_operator_catalogs,
    sync_live_models,
)
from core.database import Base, LiveModelCatalogEntry, to_utc_naive, utcnow_naive


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


if __name__ == "__main__":
    unittest.main()
