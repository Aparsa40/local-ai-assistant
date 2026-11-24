# Repository Contracts

**Project:** Local AI Assistant  
**Phase:** 4 — Storage & Memory Services  
**Work package:** WP-4.3 — Repository Services  
**Status:** Initial repository layer implemented; local validation pending

## Boundary

Repositories are infrastructure adapters for one logical data domain. They own ORM queries and persistence mechanics, but they do not decide agent permissions, assemble prompts, call providers, or perform external side effects.

Only application services and API composition code may receive repositories. Agents receive typed task data and explicit capabilities; they must never receive SQLAlchemy sessions, engines, ORM entities, or repository instances.

## Implemented repositories

| Repository | Owned tables/domain | Main operations |
|---|---|---|
| `CatalogRepository` | Operator/live catalogs, provider observations, quota snapshots, sync history, intelligence reports | Seed, sync, snapshot, record observations, save/read reports |
| `RuntimeRepository` | Runtime status, model lifecycle snapshots, runtime events | Persist one runtime observation and its event atomically |
| `ProfileRepository` | `user_profile` | Get/create profile and save profile changes |
| `SessionRepository` | `sessions` | List, get, create, rename, delete |
| `MessageRepository` | `messages` | Append and list messages in stable ID order |

No new database tables are introduced by WP-4.3.

## Transaction ownership

Transaction boundaries are intentionally explicit and preserve the current application behavior:

- Catalog operations retain their existing operation-level commits. Provider-intelligence refresh is a staged workflow: a later report failure does not erase earlier successful catalog/runtime observations.
- RuntimeRepository persists the latest runtime/model snapshots and the corresponding lifecycle event in one transaction.
- Profile, session, and message mutation methods commit their own small operation, matching the existing API's durability points.
- Read methods do not commit.
- A plain Storage Manager session does not commit implicitly.

Do not combine all provider-intelligence writes into one transaction without a separate product/operational decision and regression tests.

## Compatibility

- `core/catalog_storage.py` remains a compatibility facade delegating to `CatalogRepository`.
- `core/runtime/repository.py` re-exports the implementation from `core/repositories/runtime_repository.py`.
- Existing API routes still contain direct ORM operations for profile and conversation flows. These repositories are the foundation for the WP-4.4 service integration; this document does not claim those routes have already been migrated.
- Provider-intelligence orchestration still uses the stable catalog facade.

## Validation

Run:

```powershell
python -m pytest -q tests/test_repository_services.py tests/test_catalog_storage.py tests/test_runtime_manager.py tests/test_provider_intelligence.py
python -m pytest -q -W default
python -m compileall -q core main.py
```

The repository contract tests verify last-known-good catalog behavior, profile persistence, session CRUD/custom titles, deterministic message ordering, and runtime import compatibility.

WP-4.3 remains open until these focused tests and the full regression suite pass.


## MemoryRepository — WP-4.5

- Owns ORM access to `MemoryRecord` and explicit commit boundaries for create, update, expiry, and delete.
- Every lookup and list operation is constrained by `scope_type`, `scope_id`, and `owner_id`; services must never retrieve memory by ID alone.
- Exposes domain-oriented operations for scoped reads, exact duplicate lookup, deduplication-key lookup, lifecycle expiry, and persistence.
- Does not make activation, ranking, retention, or authorization decisions; those belong to MemoryService and its policy contracts.
- Physical deletion is explicit and commits the deletion. Expiration and supersession are lifecycle states, not hard deletion.
- No arbitrary SQL interface or repository/session object is exposed to agents.
