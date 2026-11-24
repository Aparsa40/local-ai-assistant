"""Centralized storage lifecycle and SQLite session factory."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .adapters.sqlite import SQLiteAdapter
from .config import StorageConfig
from .exceptions import StorageUnavailableError
from .session import session_scope, transaction_scope


class StorageManager:
    """Owns the database engine, session factory, and persistence health checks."""

    def __init__(
        self,
        config: StorageConfig | None = None,
        *,
        engine: Engine | None = None,
        adapter: SQLiteAdapter | None = None,
    ) -> None:
        self.config = config or StorageConfig.from_environment()
        self.engine = engine or (adapter or SQLiteAdapter()).create_engine(self.config)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

    def session(self):
        """Return a close-safe session context; no implicit commit is performed."""
        return session_scope(self.session_factory)

    def transaction(self):
        """Return an explicit transaction context with automatic rollback."""
        return transaction_scope(self.session_factory)

    def health_check(self) -> dict[str, object]:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"ok": True, "backend": "sqlite"}
        except SQLAlchemyError as exc:
            raise StorageUnavailableError("The configured database is unavailable.") from exc

    def dispose(self) -> None:
        self.engine.dispose()


_storage_manager = StorageManager()


def get_storage_manager() -> StorageManager:
    """Return the process-wide Storage Manager."""
    return _storage_manager
