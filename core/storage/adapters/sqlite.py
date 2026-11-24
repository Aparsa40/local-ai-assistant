"""SQLite engine adapter."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

from ..config import StorageConfig
from ..exceptions import StorageConfigurationError


class SQLiteAdapter:
    """Builds SQLite engines with thread-safe connections and stable in-memory tests."""

    def create_engine(self, config: StorageConfig) -> Engine:
        url = make_url(config.database_url)
        if url.get_backend_name() != "sqlite":
            raise StorageConfigurationError(
                "Only SQLite is enabled. Other database backends are future adapters."
            )

        config.ensure_database_directory()
        options = {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
            "echo": config.echo,
        }
        if url.database in {None, "", ":memory:"}:
            options["poolclass"] = StaticPool
        return create_engine(url, **options)
