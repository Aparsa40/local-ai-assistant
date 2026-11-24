"""Persistent storage and read models for operator and live model catalogs.

Operator manifests are seeded from version-controlled Python manifests. Live model
records are written only after a successful provider catalog response. Failed syncs
never delete or deactivate previously stored model records.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..database import (
    CatalogSyncHistory,
    LiveModelCatalogEntry,
    ModelRuntimeStatus,
    OperatorCatalogEntry,
    OperatorModelProfile,
    ProviderQuotaSnapshot,
    ProviderRuntimeStatus,
    ProviderIntelligenceReport,
    to_utc_naive,
    utcnow_naive,
)
from ..providers.capabilities import PROVIDER_CATALOG
from ..providers.operator_catalog import list_operator_catalogs



from .base import BaseRepository


def _iso(value):
    return value.isoformat() if value else None


class CatalogRepository(BaseRepository):
    """Persistence operations for catalog and provider-observation domains.

    The repository is bound to a caller-owned SQLAlchemy session. Existing catalog
    operations retain their explicit per-operation commit behavior for compatibility;
    WP-4.3 does not silently combine previously durable stages into one transaction.
    """

def seed_operator_catalogs(db: Session) -> int:
        """Upsert repository-owned operator manifests and curated model profiles."""
        manifests = list_operator_catalogs()
        for provider_id, manifest in manifests.items():
            entry = self.db.get(OperatorCatalogEntry, provider_id)
            if entry is None:
                entry = OperatorCatalogEntry(provider_id=provider_id, name=manifest.get("name", provider_id), manifest=manifest)
                self.db.add(entry)
            else:
                entry.name = manifest.get("name", provider_id)
                entry.manifest = manifest
    
            curated = PROVIDER_CATALOG.get(provider_id, {}).get("models", {})
            curated_model_ids = set(curated)
    
            # Reconcile this provider's persisted profiles with the current repository manifest.
            # Profiles removed from the manifest must not remain visible or enrich matching live IDs.
            stored_profiles = (
                self.db.query(OperatorModelProfile)
                .filter_by(provider_id=provider_id)
                .all()
            )
            for stored_profile in stored_profiles:
                if stored_profile.model_id not in curated_model_ids:
                    self.db.delete(stored_profile)
    
            for model_id, profile in curated.items():
                row = self.db.get(OperatorModelProfile, (provider_id, model_id))
                if row is None:
                    self.db.add(OperatorModelProfile(provider_id=provider_id, model_id=model_id, profile=profile))
                else:
                    row.profile = profile
        self.db.commit()
        return len(manifests)

def sync_live_models(
    self,
    provider_id: str,
    model_ids: list[str],
    source: str = "provider_api",
    model_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
        """Persist a successful model discovery without erasing historical records."""
        now = utcnow_naive()
        normalized_ids = list(dict.fromkeys(str(item).strip() for item in model_ids if str(item).strip()))
        existing = {
            row.model_id: row
            for row in self.db.query(LiveModelCatalogEntry).filter_by(provider_id=provider_id).all()
        }
        # An empty response is ambiguous (provider outage, permission filtering, or a genuinely empty
        # local inventory). Preserve the last known good active catalog instead of wiping it.
        if not normalized_ids and existing:
            self.db.add(CatalogSyncHistory(
                provider_id=provider_id,
                status="empty_response_preserved",
                source=source,
                discovered_count=0,
                added_count=0,
                retired_count=0,
            ))
            self.db.commit()
            return {
                "provider_id": provider_id,
                "status": "empty_response_preserved",
                "source": source,
                "discovered_count": 0,
                "added_count": 0,
                "retired_count": 0,
                "synced_at": now.isoformat(),
            }
    
        added = 0
        retired = 0
        for model_id, row in existing.items():
            if row.active and model_id not in normalized_ids:
                retired += 1
            row.active = model_id in normalized_ids
        for model_id in normalized_ids:
            row = existing.get(model_id)
            if row is None:
                row = LiveModelCatalogEntry(
                    provider_id=provider_id,
                    model_id=model_id,
                    catalog_data=(model_metadata or {}).get(model_id, {}),
                    source=source,
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                self.db.add(row)
                added += 1
            else:
                row.active = True
                row.last_seen_at = now
                row.source = source
                if model_metadata and model_id in model_metadata:
                    incoming = model_metadata[model_id] or {}
                    current = dict(row.catalog_data or {})
                    for nested_key in ("details", "model_info"):
                        if isinstance(current.get(nested_key), dict) and isinstance(incoming.get(nested_key), dict):
                            current[nested_key] = {**current[nested_key], **incoming[nested_key]}
                    current.update({key: value for key, value in incoming.items() if key not in {"details", "model_info"}})
                    if isinstance(incoming.get("details"), dict):
                        current["details"] = {**(current.get("details") or {}), **incoming["details"]}
                    if isinstance(incoming.get("model_info"), dict):
                        current["model_info"] = {**(current.get("model_info") or {}), **incoming["model_info"]}
                    row.catalog_data = current
        history = CatalogSyncHistory(
            provider_id=provider_id,
            status="success",
            source=source,
            discovered_count=len(normalized_ids),
            added_count=added,
            retired_count=retired,
        )
        self.db.add(history)
        self.db.commit()
        return {
            "provider_id": provider_id,
            "status": "success",
            "source": source,
            "discovered_count": len(normalized_ids),
            "added_count": added,
            "retired_count": retired,
            "synced_at": now.isoformat(),
        }

def record_sync_failure(self, provider_id: str, error: dict[str, Any]) -> None:
        self.db.add(CatalogSyncHistory(
            provider_id=provider_id,
            status="failed",
            source="provider_api",
            error=error,
        ))
        self.db.commit()

def record_provider_runtime(self, provider_id: str, result: dict[str, Any]) -> None:
        row = self.db.get(ProviderRuntimeStatus, provider_id)
        if row is None:
            row = ProviderRuntimeStatus(provider_id=provider_id)
            self.db.add(row)
        row.status = result.get("status", "unknown")
        row.probe = result.get("probe")
        row.model_count = result.get("model_count")
        checked_at = result.get("checked_at")
        row.checked_at = (
            to_utc_naive(datetime.fromisoformat(checked_at.replace("Z", "+00:00")))
            if checked_at
            else utcnow_naive()
        )
        row.error = result.get("error")
        row.runtime_details = result.get("runtime")
        self.db.commit()

def record_quota_snapshot(self, provider_id: str, status: dict[str, Any]) -> None:
        self.db.add(ProviderQuotaSnapshot(
            provider_id=provider_id,
            status=status,
            source=status.get("source"),
        ))
        self.db.commit()

def record_model_runtime(
    self,
    provider_id: str,
    model_id: str,
    availability: str,
    error: dict[str, Any] | None = None,
    observed_limits: dict[str, Any] | None = None,
) -> None:
        row = self.db.get(ModelRuntimeStatus, (provider_id, model_id))
        if row is None:
            row = ModelRuntimeStatus(provider_id=provider_id, model_id=model_id)
            self.db.add(row)
        row.availability = availability
        if availability == "available":
            row.last_successful_request = utcnow_naive()
            row.last_error = None
        elif error is not None:
            row.last_error = error
        if observed_limits is not None:
            row.observed_limits = observed_limits
        self.db.commit()

def get_provider_catalog_snapshot(self, provider_id: str) -> dict[str, Any]:
        operator = self.db.get(OperatorCatalogEntry, provider_id)
        profiles = self.db.query(OperatorModelProfile).filter_by(provider_id=provider_id).order_by(OperatorModelProfile.model_id).all()
        profile_by_model = {row.model_id: row.profile for row in profiles}
        live = self.db.query(LiveModelCatalogEntry).filter_by(provider_id=provider_id).order_by(LiveModelCatalogEntry.model_id).all()
        runtime = self.db.get(ProviderRuntimeStatus, provider_id)
        quota = self.db.query(ProviderQuotaSnapshot).filter_by(provider_id=provider_id).order_by(ProviderQuotaSnapshot.observed_at.desc()).first()
        history = self.db.query(CatalogSyncHistory).filter_by(provider_id=provider_id).order_by(CatalogSyncHistory.synced_at.desc()).limit(10).all()
        model_runtime = {
            row.model_id: row
            for row in self.db.query(ModelRuntimeStatus).filter_by(provider_id=provider_id).all()
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
                    "operator_profile": profile_by_model.get(row.model_id),
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
                "runtime_details": runtime.runtime_details,
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
        providers = self.db.query(OperatorCatalogEntry).order_by(OperatorCatalogEntry.provider_id).all()
        return {
            "generated_at": utcnow_naive().isoformat(),
            "providers": [self.get_provider_catalog_snapshot( row.provider_id) for row in providers],
        }

def save_intelligence_report(self, report: dict[str, Any], history_limit: int = 20) -> dict[str, Any]:
        """Persist changed report snapshots only and retain bounded per-provider/type history."""
        latest = (
            self.db.query(ProviderIntelligenceReport)
            .filter_by(provider_id=report["provider_id"], report_type=report["report_type"])
            .order_by(ProviderIntelligenceReport.generated_at.desc(), ProviderIntelligenceReport.id.desc())
            .first()
        )
        fingerprint = report.get("fingerprint")
        latest_fingerprint = (latest.report_data or {}).get("fingerprint") if latest else None
        if fingerprint and latest_fingerprint == fingerprint:
            return {
                "saved": False,
                "reason": "unchanged",
                "id": latest.id,
                "provider_id": latest.provider_id,
                "report_type": latest.report_type,
                "generated_at": latest.generated_at.isoformat(),
            }
    
        source_value = report.get("source_snapshot_at")
        source_time = None
        if source_value:
            try:
                source_time = to_utc_naive(datetime.fromisoformat(source_value.replace("Z", "+00:00")))
            except (TypeError, ValueError):
                source_time = None
        row = ProviderIntelligenceReport(
            provider_id=report["provider_id"],
            report_type=report["report_type"],
            generated_at=to_utc_naive(datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))),
            source_snapshot_at=source_time,
            overall_status=report.get("overall_status", "unknown"),
            summary=report.get("summary", ""),
            report_data=report,
            schema_version=1,
        )
        self.db.add(row)
        self.db.flush()
        stale_rows = (
            self.db.query(ProviderIntelligenceReport)
            .filter_by(provider_id=row.provider_id, report_type=row.report_type)
            .order_by(ProviderIntelligenceReport.generated_at.desc(), ProviderIntelligenceReport.id.desc())
            .offset(max(1, history_limit))
            .all()
        )
        for stale in stale_rows:
            self.db.delete(stale)
        self.db.commit()
        self.db.refresh(row)
        return {
            "saved": True,
            "reason": "changed",
            "id": row.id,
            "provider_id": row.provider_id,
            "report_type": row.report_type,
            "generated_at": row.generated_at.isoformat(),
        }

def get_latest_intelligence_report(self, provider_id: str, report_type: str | None = None) -> dict[str, Any] | None:
        query = self.db.query(ProviderIntelligenceReport).filter_by(provider_id=provider_id)
        if report_type:
            query = query.filter_by(report_type=report_type)
        row = query.order_by(ProviderIntelligenceReport.generated_at.desc(), ProviderIntelligenceReport.id.desc()).first()
        return row.report_data if row else None
