"""Configuration for the application's centralized storage layer."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class StorageConfig:
    """Runtime database configuration; SQLite is the only active backend."""

    database_url: str
    echo: bool = False
    database_path: Path | None = None

    @classmethod
    def from_environment(cls) -> "StorageConfig":
        explicit_url = os.getenv("LOCAL_AI_DATABASE_URL")
        if explicit_url:
            return cls(
                database_url=explicit_url,
                echo=os.getenv("LOCAL_AI_SQL_ECHO", "").lower() in {"1", "true", "yes"},
            )

        path = Path(os.getenv("LOCAL_AI_DATABASE_PATH", "data/chat_history.db")).expanduser()
        return cls(
            database_url=f"sqlite:///{path.as_posix()}",
            echo=os.getenv("LOCAL_AI_SQL_ECHO", "").lower() in {"1", "true", "yes"},
            database_path=path,
        )

    def ensure_database_directory(self) -> None:
        """Create the parent directory for a file-backed SQLite database."""
        url = make_url(self.database_url)
        if url.get_backend_name() != "sqlite":
            return
        database = url.database
        if database and database not in {":memory:", ""} and not database.startswith("file:"):
            Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
