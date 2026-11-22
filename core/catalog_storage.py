"""Persistent storage and read models for operator and live model catalogs.

Operator manifests are seeded from version-controlled Python manifests. Live model
records are written only after a successful provider catalog response. Failed syncs
never delete or deactivate previously stored model records.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .database import (
    CatalogSyncHistory,
    LiveModelCatalogEntry,
    ModelRuntimeStatus,
    OperatorCatalogEntry,
    OperatorModelProfile,
    ProviderQuotaSnapshot,
    ProviderRuntimeStatus,
)
from .providers.capabilities import PROVIDER_CATALOG
from .providers.operator_catalog import list_operator_catalogs


def seed_operator_catalogs(db: Session) -> int:
    """Upsert repository-owned operator manifests and curated model profiles."""
    manifests = list_operator_catalogs()
    for provider_id, manifest in manifests.items():
        entry = db.get(OperatorCatalogEntry, provider_id)
        if entry is None:
            entry = OperatorCatalogEntry(provider_id=provider_id, name=manifest.get("name", provider_id), manifest=manifest)
            db.add(entry)
        else:
            entry.name = manifest.get("name", provider_id)
            entry.manifest = manifest

        curated = PROVIDER_CATALOG.get(provider_id, {}).get("models", {})
        for model_id, profile in curated.items():
            row = db.get(OperatorModelProfile, (provider_id, model_id))
            if row is None:
                db.add(OperatorModelProfile(provider_id=provider_id, model_id=model_id, profile=profile))
            else:
                row.profile = profile
    db.commit()
    return len(manifests)


def sync_live_models(
    db: Session,
    provider_id: str,
    model_ids: list[str],
    source: str = "provider_api",
) -> dict[str, Any]:
    """Persist a successful model discovery without erasing historical records."""
    now = datetime.utcnow()
    normalized_ids = list(dict.fromkeys(str(item).strip() for item in model_ids if str(item).strip()))
    existing = {
        row.model_id: row
        for row in db.query(LiveModelCatalogEntry).filter_by(provider_id=provider_id).all()
    }
    added = 0
    for row in existing.values():
        row.active = False
    for model_id in normalized_ids:
        row = existing.get(model_id)
        if row is None:
            row = LiveModelCatalogEntry(
                provider_id=provider_id,
                model_id=model_id,
                catalog_data={},
                source=source,
                active=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(row)
            added += 1
        else:
            row.active = True
            row.last_seen_at = now
            row.source = source
    retired = sum(1 for model_id, row in existing.items() if model_id not in normalized_ids and row.active is False)
    history = CatalogSyncHistory(
        provider_id=provider_id,
        status="success",
        source=source,
        discovered_count=len(normalized_ids),
        added_count=added,
        retired_count=retired,
    )
    db.add(history)
    db.commit()
    return {
        "provider_id": provider_id,
        "status": "success",
        "source": source,
        "discovered_count": len(normalized_ids),
        "added_count": added,
        "retired_count": retired,
        "synced_at": now.isoformat(),
    }


def record_sync_failure(db: Session, provider_id: str, error: dict[str, Any]) -> None:
    db.add(CatalogSyncHistory(
        provider_id=provider_id,
        status="failed",
        source="provider_api",
        error=error,
    ))
    db.commit()


def record_provider_runtime(db: Session, provider_id: str, result: dict[str, Any]) -> None:
    row = db.get(ProviderRuntimeStatus, provider_id)
    if row is None:
        row = ProviderRuntimeStatus(provider_id=provider_id)
        db.add(row)
    row.status = result.get("status", "unknown")
    row.probe = result.get("probe")
    row.model_count = result.get("model_count")
    row.checked_at = datetime.fromisoformat(result["checked_at"].replace("Z", "+00:00")).replace(tzinfo=None) if result.get("checked_at") else datetime.utcnow()
    row.error = result.get("error")
    db.commit()


def record_quota_snapshot(db: Session, provider_id: str, status: dict[str, Any]) -> None:
    db.add(ProviderQuotaSnapshot(
        provider_id=provider_id,
        status=status,
        source=status.get("source"),
    ))
    db.commit()


def _iso(value):
    return value.isoformat() if value else None


def get_provider_catalog_snapshot(db: Session, provider_id: str) -> dict[str, Any]:
    operator = db.get(OperatorCatalogEntry, provider_id)
    profiles = db.query(OperatorModelProfile).filter_by(provider_id=provider_id).order_by(OperatorModelProfile.model_id).all()
    live = db.query(LiveModelCatalogEntry).filter_by(provider_id=provider_id).order_by(LiveModelCatalogEntry.model_id).all()
    runtime = db.get(ProviderRuntimeStatus, provider_id)
    quota = db.query(ProviderQuotaSnapshot).filter_by(provider_id=provider_id).order_by(ProviderQuotaSnapshot.observed_at.desc()).first()
    history = db.query(CatalogSyncHistory).filter_by(provider_id=provider_id).order_by(CatalogSyncHistory.synced_at.desc()).limit(10).all()
    model_runtime = {
        row.model_id: row
        for row in db.query(ModelRuntimeStatus).filter_by(provider_id=provider_id).all()
    }
    return {
        "provider_id": provider_id,
        "operator": operator.manifest if operator else {},
        "curated_models": [
            {"model_id": row.model_id, "profile": row.profile}
            for row in profiles
        ],
        "live_models": [
            {
                "model_id": row.model_id,
                "active": row.active,
                "source": row.source,
                "catalog_data": row.catalog_data or {},
                "first_seen_at": _iso(row.first_seen_at),
                "last_seen_at": _iso(row.last_seen_at),
                "runtime": {
                    "availability": model_runtime[row.model_id].availability,
                    "last_successful_request": _iso(model_runtime[row.model_id].last_successful_request),
                    "last_error": model_runtime[row.model_id].last_error,
                    "observed_limits": model_runtime[row.model_id].observed_limits,
                } if row.model_id in model_runtime else {"availability": "unknown"},
            }
            for row in live
        ],
        "provider_runtime": {
            "status": runtime.status,
            "probe": runtime.probe,
            "model_count": runtime.model_count,
            "checked_at": _iso(runtime.checked_at),
            "error": runtime.error,
        } if runtime else {"status": "unknown"},
        "quota": {
            "status": quota.status,
            "source": quota.source,
            "observed_at": _iso(quota.observed_at),
        } if quota else {"status": "unknown", "source": None, "observed_at": None},
        "sync_history": [
            {
                "status": row.status,
                "source": row.source,
                "discovered_count": row.discovered_count,
                "added_count": row.added_count,
                "retired_count": row.retired_count,
                "error": row.error,
                "synced_at": _iso(row.synced_at),
            }
            for row in history
        ],
    }


def get_operational_report(db: Session) -> dict[str, Any]:
    providers = db.query(OperatorCatalogEntry).order_by(OperatorCatalogEntry.provider_id).all()
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "providers": [get_provider_catalog_snapshot(db, row.provider_id) for row in providers],
    }
