# Memory Service

**Project:** Local AI Assistant  
**Phase:** 4 — Storage & Memory Services  
**Work package:** WP-4.5 — Memory Service  
**Status:** Implemented and locally validated (2026-11-24)  
**Branch:** `feat/phase-4-memory-service` (stacked on `feat/storage-memory-services`)

## 1. Responsibility

Memory Service stores scoped, provenance-aware facts and events for future application use. It is distinct from request Context and Knowledge Storage. It does not grant access to files, tools, connectors, or external resources.

## 2. Record contract

The `memories` table stores:

- Stable integer ID and logical type: `short_term`, `long_term`, `episodic`, or `semantic`.
- Content, optional deduplication key, owner ID, scope type, and scope ID.
- Source type/reference and required provenance JSON.
- Confidence and importance signals from 0 to 100.
- Lifecycle status, reviewer identity, and optional supersession reference.
- Retention duration, expiry, creation/update/access timestamps in UTC.

Allowed scopes are `user`, `conversation`, `task`, and `global`. Scope and owner are both part of every repository lookup; matching only a scope ID is insufficient.

## 3. Candidate and verification lifecycle

New records are always created as `candidate`. The service never creates an active memory directly. An explicit `activate(..., verified_by=...)` operation is required to promote a candidate to `active`.

Assistant-originated memories are also candidates. There is no automatic promotion based on model confidence or retrieval frequency. Retrieval excludes candidates by default; callers must explicitly opt into candidate retrieval.

Lifecycle states are:

- `candidate`: recorded but not trusted as an active memory.
- `active`: explicitly reviewed and eligible for ordinary retrieval.
- `superseded`: replaced by another active record of the same memory type and scope.
- `expired`: retention deadline has passed.
- Physical deletion: removes the row when explicitly requested and authorized.

## 4. Provenance, validation, and conflicts

Every candidate requires non-empty JSON-compatible provenance. Content and provenance are screened for common password, API-key, and bearer-token patterns; memory is not a secret store.

Deduplication is deliberately conservative:

- Exact normalized content is treated as an idempotent duplicate within the same owner, scope, and memory type.
- A repeated explicit deduplication key with different content raises `MemoryConflictError`.
- Updating content records a bounded revision history containing the previous content hash and timestamp.
- The service does not infer semantic equivalence or silently resolve conflicting facts.

## 5. Retention and retrieval

Short-term memories default to seven days. Long-term, episodic, and semantic memories have no implicit expiry; callers may specify a retention duration from 1 to 36,500 days.

Retrieval is deterministic and metadata-first. The baseline score combines:

- lexical term overlap: 55%;
- importance: 20%;
- confidence: 15%;
- freshness: 10%.

Only records with at least one lexical match are returned. Active records are retrieved by default. Results are scoped by owner and scope. Retrieval filters expired records without changing their lifecycle state; the explicit expiry operation performs the state transition. No embeddings, vector database, or hosted ranking service is required.

## 6. Access-control boundary

The `MemoryAccessPolicy` contract receives `scope_type`, `scope_id`, `owner_id`, and the requested action. The default implementation denies every operation. A caller must inject an explicit policy to use the service.

This is a privacy/default-deny integration seam only. It is not the Phase 5 Permission Manager and must not be used to imply that full authorization is complete.

## 7. Persistence and migration boundary

The ORM model is registered in `core/database.py`; the existing metadata initialization creates the `memories` table. This work package intentionally does not introduce a parallel database or a new migration framework. Versioned migrations, baseline revision, and migration tests remain WP-4.7.

## 8. Validation

Run:

```powershell
python -m pytest -q tests/test_memory_service.py
python -m pytest -q -W default
python -m compileall -q core main.py
node --check static/app.js
```

Local validation passed on 2026-11-24: `python -m pytest -q tests/test_memory_service.py tests/test_storage_manager.py` (13 passed), `python -m pytest -q -W default` (131 passed), `python -m compileall -q core main.py`, and `node --check static/app.js`. GitHub Actions also passed 131 tests, Python compilation, and frontend syntax check.

## 9. Execution directive

**Project:** Local AI Assistant  
**Phase:** 4 of 11 — Storage & Memory Services  
**Work package:** WP-4.5 — Memory Service

**Mandatory instruction:** Execute this contract exactly within WP-4.5. Keep memory owner- and scope-isolated, preserve provenance, require explicit candidate activation, and retain default-deny access behavior. Do not implement Context Manager, Knowledge ingestion, vector search, automatic extraction/promotion, or Phase 5 permissions in this work package. This document records the accepted WP-4.5 implementation and its validation evidence.
