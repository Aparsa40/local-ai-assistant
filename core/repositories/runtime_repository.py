"""Repository for local runtime state and lifecycle events.

This repository owns one short unit-of-work per runtime observation. Snapshot updates
and their corresponding lifecycle event are committed atomically.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..database import RuntimeEvent, RuntimeModelState, RuntimeStatus


class RuntimeRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def record(self, result, event_type: str) -> None:
        session = self.session_factory()
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            data = result.data if isinstance(result.data, dict) else {}
            models = data.get("models", [])
            for model in models:
                model_id = model.get("model_id")
                if not model_id:
                    continue
                row = session.get(RuntimeModelState, (result.runtime_id, model_id))
                if row is None:
                    row = RuntimeModelState(runtime_id=result.runtime_id, model_id=model_id)
                    session.add(row)
                row.state = (
                    "loaded" if model.get("loaded") is True
                    else "installed" if model.get("loaded") is False
                    else "unknown"
                )
                row.observed_at = now
                row.details = model
                row.error = None

            runtime_state_changed = False
            if result.model_id:
                row = session.get(RuntimeModelState, (result.runtime_id, result.model_id))
                if row is None:
                    row = RuntimeModelState(runtime_id=result.runtime_id, model_id=result.model_id)
                    session.add(row)
                row.observed_at = now
                if result.ok:
                    row.state = result.state
                    row.details = data
                    row.error = None
                else:
                    # Keep the last trustworthy lifecycle observation; store the failed
                    # operation separately so a failed load does not erase "installed".
                    row.error = result.error
            elif event_type not in {
                "model_inventory",
                "model_inspection",
                "model_inventory_failed",
                "model_inspection_failed",
            }:
                runtime_row = session.get(RuntimeStatus, result.runtime_id)
                if runtime_row is None:
                    runtime_row = RuntimeStatus(runtime_id=result.runtime_id)
                    session.add(runtime_row)
                    runtime_state_changed = True
                else:
                    runtime_state_changed = (
                        runtime_row.state != result.state
                        or (
                            data.get("endpoint_scope") is not None
                            and runtime_row.endpoint_scope != data.get("endpoint_scope")
                        )
                        or runtime_row.error != result.error
                    )
                runtime_row.state = result.state
                if data.get("endpoint_scope") is not None:
                    runtime_row.endpoint_scope = data.get("endpoint_scope")
                runtime_row.observed_at = now
                if event_type != "runtime_probe" or data:
                    runtime_row.details = data
                runtime_row.error = result.error

            # Polling/inspection refreshes update snapshots but do not grow the event log.
            if (
                event_type not in {"model_inventory", "model_inspection"}
                and (event_type != "runtime_probe" or runtime_state_changed)
            ):
                session.add(RuntimeEvent(
                    runtime_id=result.runtime_id,
                    model_id=result.model_id,
                    event_type=event_type,
                    state=result.state,
                    success=result.ok,
                    details=data,
                    error=result.error,
                    created_at=now,
                ))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
