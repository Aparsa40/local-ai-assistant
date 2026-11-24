# Storage Manager

**Project:** Local AI Assistant  
**Phase:** 4 — Storage & Memory Services  
**Work package:** WP-4.2 — Storage Manager  
**Status:** WP-4.2 complete — focused tests, full test suite, and compile check passed

## Purpose

The Storage Manager is the single application-owned entry point for database engine and session-factory lifecycle. SQLite is the only active backend. PostgreSQL remains a future adapter and is not implemented.

## Current database baseline

The ORM schema remains declared in `core/database.py`. The current metadata contains 14 tables:

- Conversations: `sessions`, `messages`
- Profile: `user_profile`
- Catalog: `operator_catalogs`, `operator_model_profiles`, `live_model_catalog`, `catalog_sync_history`
- Provider observations: `provider_runtime_status`, `model_runtime_status`, `provider_quota_snapshots`, `provider_intelligence_reports`
- Local runtime: `runtime_model_states`, `runtime_statuses`, `runtime_events`

These domains share one SQLite database. They do not receive separate database files.

## Configuration

| Environment variable | Purpose | Default |
|---|---|---|
| `LOCAL_AI_DATABASE_URL` | Explicit SQLAlchemy database URL; SQLite only | Unset |
| `LOCAL_AI_DATABASE_PATH` | SQLite file path when no explicit URL is provided | `data/chat_history.db` |
| `LOCAL_AI_SQL_ECHO` | Enable SQLAlchemy SQL logging (`1`, `true`, or `yes`) | Disabled |

The default database path remains `data/chat_history.db`.

## Application usage

Get the process-wide manager:

```python
from core.storage.manager import get_storage_manager

storage = get_storage_manager()
```

Use a close-safe session when an existing service owns its commit behavior:

```python
with storage.session() as db:
    # Existing domain operation; commit ownership remains explicit.
    ...
```

Use an explicit transaction when the caller owns the complete unit of work:

```python
with storage.transaction() as db:
    # All writes in this block commit together or roll back together.
    ...
```

A plain `storage.session()` does not commit implicitly. It rolls back if an exception escapes and always closes the session. `storage.transaction()` commits on success and rolls back on failure.

## Compatibility

- `core/database.py` continues to expose `engine` and `SessionLocal` as compatibility aliases.
- ORM models and `Base` remain in `core/database.py` for now.
- `main.py` obtains the manager directly and uses its session scope for request and startup sessions.
- `RuntimeRepository` still receives a session factory through dependency injection.
- `core/catalog_storage.py` still receives caller-owned SQLAlchemy sessions and retains its current internal-commit behavior. Transaction ownership will be standardized in WP-4.3, with characterization tests.

## Current limitations

- Only SQLite is enabled; unsupported database URLs fail fast.
- Foreign-key PRAGMA enforcement, busy timeout, and journal-mode policy are not yet configured.
- Versioned schema migrations are not part of WP-4.2; they belong to WP-4.7.
- Existing local database rows are disposable test data by explicit user decision. A clean database reset is permitted; no legacy-row migration or backup is required.
- Full repository/repository-service migration is not complete. Do not pass engine/session objects to agents.

## Validation

`tests/test_storage_manager.py` covers:
- SQLite directory creation and health checks;
- explicit transaction commit and rollback;
- in-memory SQLite connection stability;
- rejection of unimplemented database backends;
- creation of the current 14-table ORM schema.

Run locally:

```powershell
python -m pytest -q tests/test_storage_manager.py
python -m pytest -q
```

**Validation recorded (2026-11-24):** `python -m pytest -q tests/test_storage_manager.py` — 6 passed; `python -m pytest -q -W default` — 115 passed; `python -m compileall -q core main.py` — passed. The user confirmed all checks completed successfully. A separate live HTTP startup smoke test is not recorded here.
