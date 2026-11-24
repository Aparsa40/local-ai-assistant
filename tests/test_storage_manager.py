from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from core.storage.config import StorageConfig
from core.storage.exceptions import StorageConfigurationError
from core.storage.manager import StorageManager


def test_storage_manager_creates_sqlite_parent_directory_and_checks_health(tmp_path: Path):
    database_path = tmp_path / "nested" / "assistant.db"
    manager = StorageManager(StorageConfig(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        assert database_path.parent.is_dir()
        assert manager.health_check() == {"ok": True, "backend": "sqlite"}
    finally:
        manager.dispose()


def test_storage_manager_transaction_commits_on_success(tmp_path: Path):
    database_path = tmp_path / "transaction.db"
    manager = StorageManager(StorageConfig(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        with manager.engine.begin() as connection:
            connection.execute(text("CREATE TABLE checks (value INTEGER NOT NULL)"))

        with manager.transaction() as session:
            session.execute(text("INSERT INTO checks (value) VALUES (1)"))

        with manager.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM checks")) == 1
    finally:
        manager.dispose()


def test_storage_manager_transaction_rolls_back_on_error(tmp_path: Path):
    database_path = tmp_path / "rollback.db"
    manager = StorageManager(StorageConfig(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        with manager.engine.begin() as connection:
            connection.execute(text("CREATE TABLE checks (value INTEGER NOT NULL)"))

        with pytest.raises(RuntimeError, match="force rollback"):
            with manager.transaction() as session:
                session.execute(text("INSERT INTO checks (value) VALUES (1)"))
                raise RuntimeError("force rollback")

        with manager.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM checks")) == 0
    finally:
        manager.dispose()


def test_storage_manager_uses_one_connection_for_in_memory_sqlite():
    manager = StorageManager(StorageConfig(database_url="sqlite://"))
    try:
        with manager.engine.begin() as connection:
            connection.execute(text("CREATE TABLE checks (value INTEGER NOT NULL)"))
        with manager.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM checks")) == 0
    finally:
        manager.dispose()


def test_storage_manager_rejects_unimplemented_database_backends():
    with pytest.raises(StorageConfigurationError, match="Only SQLite is enabled"):
        StorageManager(StorageConfig(database_url="postgresql://localhost/assistant"))
