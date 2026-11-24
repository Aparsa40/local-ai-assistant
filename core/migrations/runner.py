"""Small ordered SQLite migration runner; create_all is not used as migration history."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


CURRENT_SCHEMA_REVISION = "0003_knowledge_file_versions"


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
    # Knowledge schema is created by this versioned migration, not by create_all().
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS knowledge_sources ("
        "id VARCHAR(32) PRIMARY KEY, source_type VARCHAR(20) NOT NULL, title VARCHAR(300) NOT NULL, "
        "uri TEXT, owner_id VARCHAR(160) NOT NULL, scope_type VARCHAR(40) NOT NULL, "
        "scope_id VARCHAR(160) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'registered', "
        "mime_type VARCHAR(160), byte_size INTEGER, content_hash VARCHAR(64), "
        "version INTEGER NOT NULL DEFAULT 0, metadata_json JSON NOT NULL DEFAULT '{}', "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, indexed_at DATETIME, archived_at DATETIME)"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS knowledge_files ("
        "id VARCHAR(32) PRIMARY KEY, source_id VARCHAR(32) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE, "
        "source_version INTEGER NOT NULL, storage_key VARCHAR(64) NOT NULL UNIQUE, original_filename VARCHAR(255) NOT NULL, "
        "mime_type VARCHAR(160), size_bytes INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL)"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS knowledge_chunks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "source_id VARCHAR(32) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE, "
        "ordinal INTEGER NOT NULL, content TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL, "
        "locator JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, "
        "CONSTRAINT uq_knowledge_chunk_source_ordinal UNIQUE(source_id, ordinal))"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS knowledge_artifacts ("
        "id VARCHAR(32) PRIMARY KEY, source_id VARCHAR(32) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE, "
        "source_version INTEGER NOT NULL, artifact_type VARCHAR(40) NOT NULL, content TEXT NOT NULL, "
        "status VARCHAR(20) NOT NULL DEFAULT 'unreviewed', provenance JSON NOT NULL DEFAULT '{}', "
        "created_at DATETIME NOT NULL)"
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_source_type ON knowledge_sources(source_type)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_owner_id ON knowledge_sources(owner_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_scope_type ON knowledge_sources(scope_type)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_scope_id ON knowledge_sources(scope_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_status ON knowledge_sources(status)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_content_hash ON knowledge_sources(content_hash)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_files_source_id ON knowledge_files(source_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_files_sha256 ON knowledge_files(sha256)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_source_id ON knowledge_chunks(source_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_source_ordinal ON knowledge_chunks(source_id, ordinal)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_artifacts_source_id ON knowledge_artifacts(source_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_artifacts_artifact_type ON knowledge_artifacts(artifact_type)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_artifacts_status ON knowledge_artifacts(status)",
    ):
        connection.execute(text(statement))
    tables = set(inspect(connection).get_table_names())
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
    # Rebuild the index from canonical chunk rows; this is safe if a prior attempt
    # created the virtual table but failed before recording the migration revision.
    connection.execute(text("DELETE FROM knowledge_chunks_fts"))
    connection.execute(
        text(
            "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
            "SELECT id, content, source_id FROM knowledge_chunks"
        )
    )


def _knowledge_file_versions(connection) -> None:
    columns = {item["name"] for item in inspect(connection).get_columns("knowledge_files")}
    if "source_version" not in columns:
        connection.execute(
            text("ALTER TABLE knowledge_files ADD COLUMN source_version INTEGER NOT NULL DEFAULT 1")
        )


_MIGRATIONS = (
    ("0001_legacy_additive_columns", _legacy_additive_columns),
    ("0002_knowledge_fts", _knowledge_fts),
    ("0003_knowledge_file_versions", _knowledge_file_versions),
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
