# Phase 11 — Backup, Maintenance & Integrations

**Project:** Local AI Assistant  
**Phase:** 11 of 11  
**Document type:** Authoritative execution plan  
**Status:** Planned — execution contract prepared; backup/restore and connector framework are not claimed as implemented  
**Dependencies:** Stable persistence domains from Phases 4–10; Phase 5 authorization and audit  
**Last reviewed:** 2026-11-24

## 1. Purpose and boundary

Protect the local system of record and add optional, scoped integrations. A backup is valid only when the SQLite database and managed files are captured consistently, integrity-checked, and restored successfully. Integrations must remain optional and disconnectable; they must not become the only copy of user data.

## 2. Current baseline and reuse

Current persistence includes SQLAlchemy/SQLite, versioned SQLite migrations, managed Knowledge files, runtime/catalog data, conversations, profile, memory, permissions, approvals, and audit. Reuse `core/storage/`, `core/migrations/`, `core/knowledge/storage.py`, repositories, PermissionManager, and ToolRuntime. Do not use arbitrary directory deletion or unbounded cleanup.

## 3. Scope

- Consistent database + managed-file snapshots.
- Backup manifests, hashes, schema revision, app version, and timestamps.
- Optional encryption with user-controlled key lifecycle.
- Restore verification in an isolated destination before replacing live data.
- Retention policies and safe cleanup restricted to declared cache/temp paths.
- Integrity checks and storage health diagnostics.
- Connector contract and credential isolation.
- Discord project-status integration as an optional, explicitly authorized connector.
- Sync direction, scope, conflict handling, retry, idempotency, and audit.
- Optional future hosted-readiness checklist; hosted deployment is not implied by local phase completion.

Out of scope: silent cloud backup, deleting user records to free space, storing connector tokens in ordinary settings/audit, and automatic bidirectional sync without conflict policy.

## 4. Work packages

### WP-11.1 — Data inventory and backup contract
Inventory all persistent stores, managed directories, schema revision, settings/secret sources, and runtime-generated data. Define snapshot consistency and restore invariants.
**Exit:** every user-owned persistent data domain has an explicit backup/restore classification.

### WP-11.2 — Consistent snapshot engine
Use SQLite backup API or a safe quiesce/transaction strategy; capture managed files under a stable snapshot manifest. Prevent concurrent file mutation during snapshot or record immutable versions. Include manifest hashes and schema revision.
**Exit:** a backup represents one consistent point in time and can be verified independently.

### WP-11.3 — Encryption and key lifecycle
Define supported encryption format and key derivation/handling. Keep keys outside the backup archive and ordinary logs. Require explicit user action for passphrase/key creation and recovery. A lost key must be reported as unrecoverable, not bypassed.
**Exit:** encrypted backup/restore round trip passes with correct key and fails closed with incorrect/missing key.

### WP-11.4 — Restore and disaster recovery
1. Verify manifest and every hash before restore.
2. Restore into an isolated staging directory.
3. Apply/verify schema migrations in staging.
4. Run integrity and repository smoke checks.
5. Require explicit confirmation before replacing the live database/files.
6. Keep a rollback snapshot of the pre-restore state.
**Exit:** failed restore never damages the current live data; successful restore is tested end-to-end.

### WP-11.5 — Retention and maintenance
Define backup retention, log/audit retention, orphan-file reconciliation, cache cleanup, and database maintenance. Cleanup must use allowlisted paths and never recursively delete user data. Provide dry-run reports and explicit execution.
**Exit:** maintenance actions are previewable, bounded, auditable, and reversible where possible.

### WP-11.6 — Connector framework
Define connector identity, version, scopes, credential provider, rate limits, idempotency, retry policy, webhook verification, and sync direction. Connector credentials must not be exposed to models or audit logs. Every action routes through PermissionManager and ToolRuntime.
**Exit:** connectors are disabled by default and cannot access ungranted scopes.

### WP-11.7 — Discord status connector
Implement only after generic connector contracts:
1. Define allowed repositories/channels and message schema.
2. Publish sanitized status summaries only; never send secrets, private conversations, or raw logs.
3. Define create/update behavior, deduplication keys, and conflict policy.
4. Verify bot identity and Discord API response; handle rate limits.
5. Allow disconnect/revoke without deleting local project data.
**Exit:** synchronization is explicit, scoped, idempotent, and auditable.

### WP-11.8 — Optional hosted-readiness review
Assess PostgreSQL migrations, authentication, authorization, HTTPS, CSRF/CORS, rate limits, secret vault, monitoring, backups, and operational deployment. This is a readiness review unless each item is implemented and tested; do not mark hosted multi-user security complete by documentation alone.

### WP-11.9 — Final acceptance and documentation
Run full backup/restore round-trip tests, migration compatibility tests, connector authorization tests, cleanup dry-run tests, compile, pytest, frontend syntax, and a local HTTP smoke test. Update README, architecture, roadmap, security, backup and connector docs.

## 5. Suggested implementation map

```text
core/backup/
  manifest.py
  snapshot.py
  verify.py
  restore.py
  encryption.py
core/maintenance/
  retention.py
  cleanup.py
  integrity.py
core/connectors/
  contracts.py
  registry.py
  credentials.py
  sync.py
  discord/
tests/
  test_backup_consistency.py
  test_backup_restore.py
  test_backup_encryption.py
  test_maintenance_safety.py
  test_connector_permissions.py
  test_discord_sync.py
```

## 6. Required validation

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

Use temporary isolated data roots for restore tests. Test incorrect keys, corrupted files, missing manifests, stale schema revisions, interrupted restore, rate limiting, duplicate sync events, and denied connector scopes. Never test cleanup against the user's real data directory without a dry-run and explicit approval.

## 7. Phase-wide acceptance

- Database and managed files are backed up consistently and verified by hashes.
- Restore is tested into staging and cannot damage live data on failure.
- Encryption/key lifecycle is explicit and recoverability is documented.
- Retention and cleanup never target user records or unapproved paths.
- Connector access is default-deny, scoped, revocable, and auditable.
- Discord synchronization is sanitized, idempotent, and optional.
- Disconnecting integrations does not remove local data.
- Hosted readiness is not overstated.
- Full tests, restore evidence, docs, and CI checks pass.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 11 of 11 — Backup, Maintenance & Integrations

Execute WP-11.1 through WP-11.9 in order. Protect local data above all else. Every destructive maintenance/restore operation requires a preview, explicit authorization, and a rollback strategy. External integrations must remain optional and subordinate to the local system of record.
