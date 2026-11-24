"""Shared repository primitives and session contract."""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session


class SessionLike(Protocol):
    """Minimal SQLAlchemy session surface used inside persistence adapters."""

    def add(self, instance: Any) -> None: ...
    def delete(self, instance: Any) -> None: ...
    def get(self, entity: Any, ident: Any) -> Any: ...
    def query(self, entity: Any) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def flush(self) -> None: ...
    def refresh(self, instance: Any) -> None: ...


class BaseRepository:
    """Base for infrastructure repositories; never expose its session to agents."""

    def __init__(self, session: Session | SessionLike) -> None:
        self.db = session

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
