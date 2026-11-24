"""Small ordered SQLite migration runner; create_all is not used as migration history."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


CURRENT_SCHEMA_REVISION = "0005_agent_runtime"


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
            "DELETE FROM knowledge_chunks_fts WHERE rowid = old.id; END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN "
            "DELETE FROM knowledge_chunks_fts WHERE rowid = old.id; "
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


def _knowledge_fts_trigger_fix(connection) -> None:
    # FTS5's special 'delete' command caused SQLite logic errors in bulk chunk replacement.
    # Direct rowid deletion is supported by the normal FTS5 content table and is simpler.
    connection.execute(text("DROP TRIGGER IF EXISTS knowledge_chunks_ai"))
    connection.execute(text("DROP TRIGGER IF EXISTS knowledge_chunks_ad"))
    connection.execute(text("DROP TRIGGER IF EXISTS knowledge_chunks_au"))
    connection.execute(text(
        "CREATE TRIGGER knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
        "VALUES (new.id, new.content, new.source_id); END"
    ))
    connection.execute(text(
        "CREATE TRIGGER knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN "
        "DELETE FROM knowledge_chunks_fts WHERE rowid = old.id; END"
    ))
    connection.execute(text(
        "CREATE TRIGGER knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN "
        "DELETE FROM knowledge_chunks_fts WHERE rowid = old.id; "
        "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
        "VALUES (new.id, new.content, new.source_id); END"
    ))
    connection.execute(text("DELETE FROM knowledge_chunks_fts"))
    connection.execute(text(
        "INSERT INTO knowledge_chunks_fts(rowid, content, source_id) "
        "SELECT id, content, source_id FROM knowledge_chunks"
    ))




def _agent_runtime(connection) -> None:
    # Agent Runtime schema is created by this versioned migration, not create_all().
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS agent_definitions ("
        "agent_id VARCHAR(80) NOT NULL, version VARCHAR(40) NOT NULL, "
        "goal TEXT NOT NULL, description TEXT NOT NULL, "
        "input_schema JSON NOT NULL DEFAULT '{}', output_schema JSON NOT NULL DEFAULT '{}', "
        "completion_kind VARCHAR(60) NOT NULL, completion_description TEXT NOT NULL, "
        "completion_min_results INTEGER NOT NULL DEFAULT 1, "
        "budget_max_iterations INTEGER NOT NULL DEFAULT 12, "
        "budget_deadline_seconds INTEGER NOT NULL DEFAULT 300, "
        "budget_max_tool_calls INTEGER NOT NULL DEFAULT 20, "
        "budget_max_model_tokens INTEGER NOT NULL DEFAULT 20000, "
        "budget_max_input_bytes INTEGER NOT NULL DEFAULT 65536, "
        "budget_max_output_bytes INTEGER NOT NULL DEFAULT 262144, "
        "allowed_tools JSON NOT NULL DEFAULT '[]', allowed_models JSON NOT NULL DEFAULT '[]', "
        "data_scopes JSON NOT NULL DEFAULT '[]', "
        "approval_policy VARCHAR(40) NOT NULL DEFAULT 'explicit', "
        "enabled BOOLEAN NOT NULL DEFAULT 1, registered_at DATETIME NOT NULL, "
        "updated_at DATETIME NOT NULL, PRIMARY KEY (agent_id, version))"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS agent_tasks ("
        "task_id VARCHAR(32) PRIMARY KEY, agent_id VARCHAR(80) NOT NULL, "
        "agent_version VARCHAR(40) NOT NULL, owner_id VARCHAR(160) NOT NULL, "
        "title VARCHAR(200) NOT NULL, payload JSON NOT NULL DEFAULT '{}', "
        "data_scopes JSON NOT NULL DEFAULT '[]', "
        "status VARCHAR(20) NOT NULL DEFAULT 'open', created_at DATETIME NOT NULL, "
        "updated_at DATETIME NOT NULL)"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS agent_runs ("
        "run_id VARCHAR(32) PRIMARY KEY, task_id VARCHAR(32) NOT NULL, "
        "agent_id VARCHAR(80) NOT NULL, agent_version VARCHAR(40) NOT NULL, "
        "owner_id VARCHAR(160) NOT NULL, trace_id VARCHAR(80) NOT NULL, "
        "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
        "scope_type VARCHAR(40) NOT NULL, scope_id VARCHAR(160) NOT NULL, "
        "version INTEGER NOT NULL DEFAULT 1, attempt INTEGER NOT NULL DEFAULT 1, "
        "iteration INTEGER NOT NULL DEFAULT 0, tool_calls INTEGER NOT NULL DEFAULT 0, "
        "model_tokens INTEGER NOT NULL DEFAULT 0, "
        "last_checkpoint_sequence INTEGER NOT NULL DEFAULT 0, "
        "pending_approval_id VARCHAR(80), stop_reason VARCHAR(40), "
        "error_code VARCHAR(80), error_message TEXT, outcome JSON, "
        "created_at DATETIME NOT NULL, started_at DATETIME, updated_at DATETIME, "
        "finished_at DATETIME)"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS agent_run_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, event_id VARCHAR(32) NOT NULL UNIQUE, "
        "run_id VARCHAR(32) NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE, "
        "ordinal INTEGER NOT NULL, event_type VARCHAR(80) NOT NULL, "
        "outcome VARCHAR(40) NOT NULL, metadata_json JSON NOT NULL DEFAULT '{}', "
        "created_at DATETIME NOT NULL)"
    ))
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS agent_checkpoints ("
        "checkpoint_id VARCHAR(32) PRIMARY KEY, "
        "run_id VARCHAR(32) NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE, "
        "sequence INTEGER NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1, "
        "payload JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, "
        "CONSTRAINT uq_agent_checkpoint_run_sequence UNIQUE(run_id, sequence))"
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_agent_definitions_agent_id ON agent_definitions(agent_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_agent_id ON agent_tasks(agent_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_owner_id ON agent_tasks(owner_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_status ON agent_tasks(status)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_task_id ON agent_runs(task_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_id ON agent_runs(agent_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_owner_id ON agent_runs(owner_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_trace_id ON agent_runs(trace_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_status ON agent_runs(status)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_scope_id ON agent_runs(scope_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_task_status ON agent_runs(task_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_id ON agent_run_events(run_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_run_events_event_type ON agent_run_events(event_type)",
        "CREATE INDEX IF NOT EXISTS ix_agent_run_events_created_at ON agent_run_events(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_agent_checkpoints_run_id ON agent_checkpoints(run_id)",
    ):
        connection.execute(text(statement))

_MIGRATIONS = (
    ("0001_legacy_additive_columns", _legacy_additive_columns),
    ("0002_knowledge_fts", _knowledge_fts),
    ("0003_knowledge_file_versions", _knowledge_file_versions),
    ("0004_knowledge_fts_trigger_fix", _knowledge_fts_trigger_fix),
    ("0005_agent_runtime", _agent_runtime),
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
