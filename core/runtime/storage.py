"""Persistence adapter for normalized runtime observations.

This module writes observations into the existing catalog/runtime tables. It does
not create a parallel runtime database or treat persisted state as live truth.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from core.database import (
    LiveModelCatalogEntry,
    ProviderRuntimeStatus,
    utcnow_naive,
)
from .contracts import ModelObservation, RuntimeProbe, RuntimeState


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return utcnow_naive()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        from datetime import timezone
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def persist_runtime_snapshot(
    db: Session,
    probe: RuntimeProbe,
    installed_models: list[ModelObservation],
    loaded_models: list[ModelObservation] | None,
) -> None:
    """Persist one coherent runtime observation; None loaded_models means unknown."""
    runtime = db.get(ProviderRuntimeStatus, probe.runtime_id)
    if runtime is None:
        runtime = ProviderRuntimeStatus(provider_id=probe.runtime_id)
        db.add(runtime)

    status_map = {
        RuntimeState.READY: "reachable",
        RuntimeState.UNAVAILABLE: "unreachable",
        RuntimeState.NOT_INSTALLED: "not_installed",
        RuntimeState.FAILED: "error",
    }
    runtime.status = status_map.get(probe.state, "unknown")
    runtime.probe = "local_model_runtime"
    runtime.model_count = len(installed_models)
    runtime.checked_at = _parse_timestamp(probe.checked_at)
    runtime.error = (
        {"category": probe.error_category, "message": probe.message}
        if probe.error_category or probe.message else None
    )
    runtime.runtime_details = {
        "runtime_id": probe.runtime_id,
        "state": probe.state.value,
        "endpoint_scope": probe.endpoint_scope,
        "already_running": probe.already_running,
        "started_by_application": probe.started_by_application,
        "process_id": probe.process_id,
        "details": probe.details,
        "source": "local_model_runtime",
    }

    loaded_by_id = {
        model.model_id: model for model in (loaded_models or [])
    }
    loaded_is_known = loaded_models is not None
    for model in installed_models:
        row = db.get(LiveModelCatalogEntry, (model.runtime_id, model.model_id))
        if row is None:
            row = LiveModelCatalogEntry(
                provider_id=model.runtime_id,
                model_id=model.model_id,
                catalog_data={},
                source="runtime_observation",
                active=True,
            )
            db.add(row)

        catalog_data = dict(row.catalog_data or {})
        previous = dict(catalog_data.get("runtime_observation") or {})
        loaded = loaded_by_id.get(model.model_id)
        if loaded is not None:
            loaded_value = True
            loaded_source = loaded.source
            loaded_at = loaded.observed_at
        elif loaded_is_known:
            loaded_value = False
            loaded_source = "ollama_api_ps"
            loaded_at = probe.checked_at
        else:
            loaded_value = None
            loaded_source = "unknown"
            loaded_at = probe.checked_at

        catalog_data["runtime_observation"] = {
            **previous,
            "installed": True,
            "loaded": loaded_value,
            "installed_source": model.source,
            "loaded_source": loaded_source,
            "observed_at": probe.checked_at,
            "loaded_observed_at": loaded_at,
        }
        row.catalog_data = catalog_data
        row.active = True
        row.last_seen_at = _parse_timestamp(probe.checked_at)

    db.commit()
