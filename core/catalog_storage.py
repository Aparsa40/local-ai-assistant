"""Compatibility service facade for catalog and provider-observation persistence.

New application code should depend on CatalogRepository through an explicit service
boundary. These functions remain stable for current API routes and provider workflows.
"""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from .repositories.catalog_repository import CatalogRepository


def seed_operator_catalogs(db: Session) -> int:
    return CatalogRepository(db).seed_operator_catalogs()


def sync_live_models(db: Session, provider_id: str, model_ids: list[str], source: str = "provider_api", model_metadata: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    return CatalogRepository(db).sync_live_models(provider_id, model_ids, source, model_metadata)


def record_sync_failure(db: Session, provider_id: str, error: dict[str, Any]) -> None:
    return CatalogRepository(db).record_sync_failure(provider_id, error)


def record_provider_runtime(db: Session, provider_id: str, result: dict[str, Any]) -> None:
    return CatalogRepository(db).record_provider_runtime(provider_id, result)


def record_quota_snapshot(db: Session, provider_id: str, status: dict[str, Any]) -> None:
    return CatalogRepository(db).record_quota_snapshot(provider_id, status)


def record_model_runtime(db: Session, provider_id: str, model_id: str, availability: str, error: dict[str, Any] | None = None, observed_limits: dict[str, Any] | None = None) -> None:
    return CatalogRepository(db).record_model_runtime(provider_id, model_id, availability, error, observed_limits)


def get_provider_catalog_snapshot(db: Session, provider_id: str) -> dict[str, Any]:
    return CatalogRepository(db).get_provider_catalog_snapshot(provider_id)


def get_operational_report(db: Session) -> dict[str, Any]:
    return CatalogRepository(db).get_operational_report()


def save_intelligence_report(db: Session, report: dict[str, Any], history_limit: int = 20) -> dict[str, Any]:
    return CatalogRepository(db).save_intelligence_report(report, history_limit)


def get_latest_intelligence_report(db: Session, provider_id: str, report_type: str | None = None) -> dict[str, Any] | None:
    return CatalogRepository(db).get_latest_intelligence_report(provider_id, report_type)
