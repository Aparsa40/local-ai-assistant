"""SQLAlchemy persistence adapter for local runtime state and lifecycle events."""
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
            models = result.data.get("models", []) if isinstance(result.data, dict) else []
            for model in models:
                model_id = model.get("model_id")
                if not model_id:
                    continue
                row = session.get(RuntimeModelState, (result.runtime_id, model_id))
                if row is None:
                    row = RuntimeModelState(runtime_id=result.runtime_id, model_id=model_id)
                    session.add(row)
                row.state = "loaded" if model.get("loaded") is True else "installed" if model.get("loaded") is False else "unknown"
                row.observed_at = now
                row.details = model
                row.error = None
            if not result.model_id:
                runtime_row = session.get(RuntimeStatus, result.runtime_id)
                if runtime_row is None:
                    runtime_row = RuntimeStatus(runtime_id=result.runtime_id)
                    session.add(runtime_row)
                runtime_row.state = result.state
                runtime_row.endpoint_scope = (result.data or {}).get("endpoint_scope")
                runtime_row.observed_at = now
                runtime_row.details = result.data or {}
                runtime_row.error = result.error
            if result.model_id:
                row = session.get(RuntimeModelState, (result.runtime_id, result.model_id))
                if row is None:
                    row = RuntimeModelState(runtime_id=result.runtime_id, model_id=result.model_id)
                    session.add(row)
                row.state = result.state
                row.observed_at = now
                row.details = result.data or {}
                row.error = result.error
            if event_type not in {"model_inventory", "model_inspection"}:
                session.add(RuntimeEvent(
                    runtime_id=result.runtime_id,
                model_id=result.model_id,
                event_type=event_type,
                state=result.state,
                success=result.ok,
                details=result.data or {},
                error=result.error,
                    created_at=now,
                ))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
