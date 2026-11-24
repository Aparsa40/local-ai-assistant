"""Small ordered SQLite migration runner; create_all is not used as migration history."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


CURRENT_SCHEMA_REVISION = "0002_knowledge_fts"


def _legacy_additive_columns(connection) -> None:
    tables = set(inspect(connection).get_table_names())
    if "sessions" in tables:
        columns = {item["name"] for item in inspect(connection).get_columns("sessions")}
        if "title_is_custom" not in columns:
            connection.execute(
                text("ALTER TABLE sessions ADD COLUMN title_is_custom BOOLEAN NOT NULL DEFAULT 0")
            )
    if "provider_runtime_status" in tables:
        columns = {item["name"] for item in inspect(connection).get_columns("provider_runtime_status")}
        if "runtime_details" not in columns:
            connection.execute(
                text("ALTER TABLE provider_runtime_status ADD COLUMN runtime_details JSON")
            )


def _knowledge_fts(connection) -> None:
    tables = set(inspect(connection).get_table_names())
    if "knowledge_chunks" not in tables:
        raise RuntimeError("Knowledge ORM tables must exist before the FTS migration")
    connection.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts "
            "USING fts5(content, source_id UNINDEXED, tokenize='unicode61')"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN "
            "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
            "VALUES (new.id, new.content, new.source_id); END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN "
            "INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, content, source_id) "
            "VALUES ('delete', old.id, old.content, old.source_id); END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN "
            "INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, content, source_id) "
            "VALUES ('delete', old.id, old.content, old.source_id); "
            "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
            "VALUES (new.id, new.content, new.source_id); END"
        )
    )
    # Backfill chunks created before FTS was introduced. A migration runs only once.
    connection.execute(
        text(
            "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
            "SELECT id, content, source_id FROM knowledge_chunks"
        )
    )


_MIGRATIONS = (
    ("0001_legacy_additive_columns", _legacy_additive_columns),
    ("0002_knowledge_fts", _knowledge_fts),
)


def run_migrations(engine: Engine) -> str:
    """Apply each migration once, in order, and return the current revision."""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Versioned migrations currently support SQLite only")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "revision VARCHAR(80) PRIMARY KEY, "
                "applied_at VARCHAR(40) NOT NULL)"
            )
        )
    for revision, migration in _MIGRATIONS:
        with engine.begin() as connection:
            applied = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE revision = :revision"),
                {"revision": revision},
            ).first()
            if applied:
                continue
            migration(connection)
            connection.execute(
                text(
                    "INSERT INTO schema_migrations(revision, applied_at) "
                    "VALUES (:revision, :applied_at)"
                ),
                {
                    "revision": revision,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    return CURRENT_SCHEMA_REVISION
