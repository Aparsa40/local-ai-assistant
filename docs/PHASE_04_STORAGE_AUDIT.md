# Phase 4 — WP-4.1 Storage Audit & Contracts

**Project:** Local AI Assistant  
**Phase:** 4 of 11 — Storage & Memory Services  
**Work package:** WP-4.1 — Storage Audit & Contracts  
**Status:** WP-4.1 complete — working contracts accepted; WP-4.2 implementation in progress  
**Branch:** `feat/storage-memory-services`  
**Baseline:** `main` after PR #9  
**Last reviewed:** 2026-11-24

## 1. Purpose and audit boundary

This document records the evidence-based audit and working storage contracts for the current persistence implementation. It is the implementation baseline for Phase 4, not a proposal to replace the whole database stack.

The user has explicitly confirmed that the current local database contains disposable test conversations only. Preserving pre-Phase-4 rows or providing a migration path for those test records is not a requirement. The application must still create and use a clean, functional schema. This decision removes the need to inspect or back up the user's live SQLite file before implementation.

### Sources inspected

- `core/database.py`
- `core/catalog_storage.py`
- `core/runtime/repository.py`
- `main.py`
- `core/runtime/manager.py`
- `docs/ARCHITECTURE.md`
- `docs/PROJECT_PRINCIPLES.md`
- `docs/CATALOG_STORAGE.md`
- `docs/PERMISSIONS.md`
- `docs/PHASE_04_EXECUTION_PLAN.md`

**Coverage note:** the principal production persistence paths, ORM declarations, transaction ownership, runtime repository, provider-intelligence workflow, and related tests were inspected. The GitHub connector did not provide a reliable repository tree/code-search inventory, so this is a practical architecture-level inventory rather than a claim that every incidental SQLAlchemy reference in every file was exhaustively enumerated. The current evidence is sufficient to establish the Storage Manager boundary; remaining call sites will be handled as they are migrated and covered by tests.

## 2. Current physical storage topology

### 2.1 Physical database

The application uses one local SQLite database. The original implementation created its engine and session factory in `core/database.py`; WP-4.2 has now moved that lifecycle into `core/storage/manager.py`.

- Default path: `data/chat_history.db`
- Engine and session factory owner: process-wide `StorageManager`
- ORM metadata: `Base` remains in `core/database.py`
- SQLite connection option: `check_same_thread=False`
- Schema initialization: `init_db()` still calls `Base.metadata.create_all()` and retains the two existing additive column checks.
- Compatibility: `core/database.py` re-exports `engine` and `SessionLocal` while existing callers are migrated incrementally.

There is no evidence in the inspected implementation of separate physical databases per module or agent. The architecture explicitly allows multiple logical data domains to share one physical database. **Do not create one SQLite file per agent or domain by default.**

PostgreSQL is a future compatibility target only. It is not an operational adapter in this phase baseline and must not be represented as implemented.

### 2.2 Logical data domains

| Logical domain | Current tables | Data owner (target boundary) | Current implementation |
|---|---|---|---|
| Conversations | `sessions`, `messages` | Conversation Storage | ORM models in `core/database.py`; route-level access in `main.py` |
| User profile | `user_profile` | Profile Repository / Profile service boundary | ORM model and route-level access in `main.py` |
| Operator catalog | `operator_catalogs`, `operator_model_profiles` | Catalog domain | `core/catalog_storage.py`; source manifests under `core/providers/` |
| Live model catalog | `live_model_catalog` | Catalog domain | `core/catalog_storage.py` |
| Provider observations | `provider_runtime_status`, `model_runtime_status`, `provider_quota_snapshots`, `catalog_sync_history`, `provider_intelligence_reports` | Provider Intelligence / Catalog domain | `core/catalog_storage.py` and provider-intelligence workflows |
| Local runtime | `runtime_model_states`, `runtime_statuses`, `runtime_events` | Local Model Runtime | `core/runtime/repository.py` |
| Memory | None identified | Memory Service (planned) | Not implemented |
| Request context | None identified as a persistent domain | Context Manager (planned; request-scoped) | Not implemented |
| Knowledge metadata / search | None identified | Knowledge Storage (planned) | Not implemented |
| Managed original files | No dedicated storage adapter identified | File Storage (planned) | Not implemented as a managed abstraction |

Logical ownership does not imply a separate physical database. Each domain must expose an owned repository/service boundary and must not mutate another domain's records directly.

## 3. Current schema inventory

The following inventory is derived from ORM declarations in `core/database.py`.

| Table | Primary key | Relationships / notable fields | Intended owner |
|---|---|---|---|
| `sessions` | `id` | `title`, `title_is_custom`, `created_at`; ORM relationship to messages with `all, delete-orphan` | Conversation |
| `messages` | `id` | `session_id` references `sessions.id`; role, content, model, timestamp | Conversation |
| `user_profile` | `id` | display name, username, email, avatar bytes and MIME type | Profile |
| `operator_catalogs` | `provider_id` | name, JSON manifest, updated timestamp | Catalog |
| `operator_model_profiles` | `provider_id + model_id` | JSON curated profile | Catalog |
| `live_model_catalog` | `provider_id + model_id` | JSON provider metadata, source, active flag, first/last seen | Catalog |
| `provider_runtime_status` | `provider_id` | probe status, model count, check time, error/runtime JSON | Provider Intelligence |
| `model_runtime_status` | `provider_id + model_id` | observed availability, last success/error, limits | Provider Intelligence |
| `provider_quota_snapshots` | `id` | provider ID, JSON status/source, observation time | Provider Intelligence |
| `catalog_sync_history` | `id` | provider ID, result, counts, error, sync time | Catalog |
| `provider_intelligence_reports` | `id` | provider ID/type, source timestamp, status, report JSON, schema version | Provider Intelligence |
| `runtime_model_states` | `runtime_id + model_id` | lifecycle state, observation, details/error JSON | Local Runtime |
| `runtime_statuses` | `runtime_id` | runtime state, endpoint scope, details/error JSON | Local Runtime |
| `runtime_events` | `id` | runtime/model, event type, state, success, details/error, created time | Local Runtime |

### 3.1 Relationship and integrity observations

- `messages.session_id` has a foreign key to `sessions.id`, but the inspected declaration does not specify `nullable=False` or database-level `ON DELETE CASCADE`.
- The `ChatSession.messages` ORM relationship uses `cascade="all, delete-orphan"`. ORM cascade semantics must not be confused with a database-level cascade guarantee for raw SQL or external writers.
- Catalog and runtime tables mostly use provider/runtime identifiers as logical references; no foreign keys to provider manifests or catalog rows were identified in the inspected declarations.
- JSON columns contain flexible provider/runtime payloads. Their shape/versioning and redaction rules need explicit contracts before they are reused as general-purpose agent state.
- `UserProfile.avatar_data` stores binary image data in SQLite. This is a current exception to the target preference for managed file storage; do not move it until compatibility, size, and migration behavior are designed and tested.
- Existing IDs and table names are compatibility-sensitive. No duplicate replacement conversation tables should be introduced.

## 4. Engine, session, and transaction findings

### 4.1 Engine/session creation

| Location | Observed behavior | Audit classification |
|---|---|---|
| `core/database.py` | Defines ORM metadata and exports compatibility aliases for `engine` and `SessionLocal` | ORM/schema module; engine lifecycle delegated to Storage Manager |
| `main.py:get_db()` | Creates one session per FastAPI dependency scope and closes it in `finally` | Existing request-scoped session pattern |
| `main.py` startup | Calls `init_db()`; builds runtime manager with `SessionLocal`; seeds catalog using a context-managed session | Multiple lifecycle entry points tied to the module-level factory |
| `core/runtime/repository.py:record()` | Creates its own session from injected factory; commits, rolls back on exception, closes in `finally` | Repository owns its unit of work |
| `core/catalog_storage.py` | Receives a caller-owned `Session`; several write functions commit internally | Transaction ownership is mixed between caller and domain storage functions |

No second `create_engine()` or `sessionmaker()` was observed in the files inspected. This is not yet proof that the entire repository has no other creation site.

### 4.2 Transaction ownership and consistency risks

1. **Mixed commit ownership:** catalog storage functions such as catalog seeding, live-model synchronization, sync failure recording, runtime observations, quota snapshots, and model runtime updates commit internally. Other operations read through the same caller-supplied session. This makes larger application-level atomic workflows difficult to compose.
2. **Route-level writes:** profile creation/update/avatar routes and other application paths in `main.py` directly mutate ORM entities and call `commit()`. These operations have not yet been moved behind domain repositories.
3. **Runtime repository isolation:** `RuntimeRepository.record()` creates and closes its own session and has an explicit rollback path. This is a useful existing seam, but its unit-of-work contract differs from catalog storage.
4. **Schema evolution:** `init_db()` relies on `create_all()` plus inline checks for `sessions.title_is_custom` and `provider_runtime_status.runtime_details`. This is not a versioned migration history and does not establish a repeatable migration baseline.
5. **SQLite settings:** `check_same_thread=False` is configured, but the inspected engine setup does not establish a documented busy-timeout, journal-mode, foreign-key enforcement, or concurrency policy. These must be measured and tested, not changed speculatively.
6. **Startup side effects:** importing/starting the FastAPI application invokes schema initialization and catalog seeding. WP-4.2 must preserve startup behavior while making lifecycle/test boundaries explicit.
7. **Failure atomicity:** each multi-row catalog/runtime operation needs an explicit transaction contract and tests proving that partial writes roll back safely.

## 5. Current caller and access map

This map is limited to the inspected source files and must be extended after the repository-wide call-site pass.

| Caller / component | Current data access | Current authority observed | Target boundary |
|---|---|---|---|
| FastAPI routes in `main.py` | Direct `SessionLocal` dependency, ORM queries and entity mutation for profile; imports conversation models for chat routes | Broad application-level DB access | Conversation/Profile/Catalog repositories and services |
| `core/catalog_storage.py` | Direct ORM queries and writes across catalog and provider-observation tables | Catalog domain storage functions | Catalog and Provider Observation repositories |
| `core/runtime/repository.py` | Direct ORM access to runtime state/event tables | Local Runtime persistence adapter | Runtime Repository interface |
| `core/runtime/manager.py` | Calls injected repository's `record()`; no ORM imports observed | Runtime service delegates persistence | Keep ORM-free |
| `core/runtime/factory.py` (not yet inspected in this pass) | Runtime manager is built with `SessionLocal` from app startup | Injection seam indicated by `main.py` | Verify factory wiring and keep session factory behind Storage Manager |
| `core/provider_intelligence.py` | Imports `catalog_storage` and `utcnow_naive`; orchestrates local Ollama process lifecycle and report analysis; uses catalog storage for persisted observations/reports | Provider Intelligence service delegates persistence to catalog storage; complete function-level call graph still pending | Keep runtime process control separate from persistence; route data writes through catalog-owned repository contracts |
| Interface Manager | No ORM import observed in inspected architecture; catalog service access is indirect | Provider/model control-plane service | Must consume catalog contracts, not SQLAlchemy sessions |


## 5.1 Second-pass call-site evidence (2026-11-24)

The following source files were fetched directly from `main` and inspected beyond the initial pass: `core/database.py`, `core/catalog_storage.py`, `core/provider_intelligence.py`, `core/runtime/repository.py`, `core/runtime/factory.py`, `core/runtime/manager.py`, `core/runtime/monitor.py`, `core/interface_manager.py`, `core/orchestrator.py`, `core/providers/base.py`, `core/providers/registry.py`, `core/config_manager.py`, and the relevant storage/runtime/provider tests. The API routes in `main.py` were inspected in full.

### Confirmed database access sites

| File / function | Operation | Domain | Finding / WP-4.1 classification |
|---|---|---|---|
| `core/database.py` module scope | `create_engine()`, `sessionmaker()` | Shared database | Only confirmed production engine/session-factory construction site in inspected production modules; move lifecycle ownership behind Storage Manager in WP-4.2 |
| `core/database.py:init_db()` | `Base.metadata.create_all()`, two `ALTER TABLE` statements | Schema lifecycle | Unversioned schema evolution; preserve current behavior until migration baseline and startup contract are approved |
| `main.py:get_db()` | Creates and closes `SessionLocal` | Request unit of work | Existing FastAPI session dependency; replace implementation behind a provider/dependency seam, not route-by-route engine access |
| `main.py:get_or_create_profile()` | ORM query, insert, commit, refresh | Profile | Route-layer persistence; move to Profile Repository/Service |
| `main.py:update_profile()`, avatar upload/delete | Mutate profile row, commit/refresh | Profile | Route-layer persistence; avatar BLOB remains compatibility-sensitive |
| `main.py` session CRUD routes | Query/create/delete/rename sessions and read messages | Conversation | Direct ORM access in API layer; move behind Conversation Repository without changing response contracts |
| `main.py:chat_endpoint()` | Reads session/history, commits title and user message | Conversation | Multiple commits before provider inference; preserve user-message durability if inference fails |
| `main.py:response_generator()` | Opens separate diagnostic/assistant sessions; records model runtime and assistant message | Conversation + Provider observation | Streaming response uses fresh sessions after response begins; preserve this lifecycle and atomicity semantics |
| `main.py` provider/catalog/report routes | Calls catalog read/write functions using request session | Catalog / Provider Intelligence | Routes orchestrate workflows but still pass raw SQLAlchemy Session to service functions |
| `main.py:provider_quota_status()` | Calls quota provider, then persists snapshot | Provider observation | Domain write currently invoked from API route via storage function |
| `core/provider_intelligence.py:refresh_provider_intelligence()` | Reads snapshots and calls record/sync/report persistence functions | Provider Intelligence / Catalog | Service receives raw Session; persistence is split into multiple commits |
| `core/provider_intelligence.py:create_offline_intelligence_report()` | Builds report from persisted snapshot and saves report | Provider Intelligence | Service receives raw Session; report save owns commit |
| `core/catalog_storage.py` | ORM reads/writes for operator, live model, provider runtime, quota, model runtime, sync history, reports | Catalog / Provider observation | Domain storage module owns table access, but write helpers commit internally |
| `core/runtime/repository.py:record()` | ORM upserts snapshots, appends events, commits/rolls back/closes | Local Runtime | Clear repository seam; repository owns an independent transaction per record |
| `core/runtime/factory.py:build_runtime_manager()` | Injects session factory into RuntimeRepository | Composition root | Good dependency-injection seam; target should inject repository built from Storage Manager rather than raw global factory |

### Transaction and unit-of-work findings confirmed

- `catalog_storage.seed_operator_catalogs()`, `sync_live_models()`, `record_sync_failure()`, `record_provider_runtime()`, `record_quota_snapshot()`, `record_model_runtime()`, and `save_intelligence_report()` call `commit()` internally on caller-owned sessions.
- `save_intelligence_report()` calls `flush()` before pruning history and committing, so the insert and history pruning are currently committed together within that helper.
- `refresh_provider_intelligence()` calls `record_provider_runtime()` before model sync/failure recording and report persistence. Those helpers commit separately. A later report failure therefore does not roll back earlier provider observations or model catalog synchronization. This may be intentional staged durability; the target contract must explicitly decide whether refresh is one atomic unit or a sequence of independently durable observations.
- `RuntimeRepository.record()` owns its session and transaction, including rollback on any exception and close in `finally`. Keep this explicit isolation or replace it with an equally explicit Unit of Work contract.
- `main.py:chat_endpoint()` commits the user's message before calling the model. The assistant response is persisted only after successful stream completion, using a new session. This means a provider failure intentionally leaves the user message persisted without an assistant response; preserve unless a product-level decision changes it.
- `main.py` calls `init_db()` and seeds operator catalogs during module import/application construction. Test isolation and startup ordering must be explicit in the Storage Manager migration.
- `get_provider_catalog()` contains an `owns_session = not isinstance(db, Session)` fallback even though FastAPI normally injects a real Session through `Depends(get_db)`; verify whether any direct non-request caller depends on this behavior before removing it.

### Test evidence

- `tests/test_catalog_storage.py` uses in-memory SQLite, `StaticPool`, a fresh engine, and `Base.metadata.create_all()`. It covers timestamp normalization, operator seeding/reconciliation, live catalog retention, failed sync behavior, metadata merge, bounded report history, runtime details, and the additive `runtime_details` migration.
- `tests/test_runtime_manager.py` uses isolated in-memory SQLite and verifies RuntimeRepository snapshot/event persistence, repeated probe event suppression, and preservation of known model state on failed operations.
- `tests/test_provider_intelligence.py` uses a helper-created in-memory SQLite database and exercises provider/runtime/report workflows.
- No dedicated `tests/test_database.py`, `tests/test_runtime_repository.py`, or `tests/test_api.py` exists at the guessed paths on `main`; this does not imply absence of other test modules. A full tracked-file inventory remains blocked because repository code search returned no indexed results and the available GitHub connector does not expose a repository tree listing operation in this workflow.

### Additional contract implications

1. Catalog storage functions currently mix repository responsibilities with transaction ownership. WP-4.2 should first introduce a stable Unit of Work/transaction convention and characterization tests; do not simply remove internal commits in a broad mechanical edit.
2. Conversation and Profile repositories must preserve route-level HTTP behavior, current IDs, ordering, title auto-generation/custom-title rules, and the two-phase user/assistant message persistence.
3. Runtime snapshots and append-only events are different data products; do not collapse them into one table or treat every poll as an event.
4. Provider runtime observations, catalog synchronization, quota snapshots, and intelligence reports have different retention and durability semantics. Keep their logical contracts separate even if they remain in the same SQLite file.
5. `InterfaceManager`, `RuntimeManager`, `RuntimeMonitor`, `Orchestrator`, and provider adapters inspected in this pass do not import SQLAlchemy or directly access the database. Preserve this ORM-free boundary. Interface Manager currently reads version-controlled operator manifests/capability definitions; persisted catalog writes are performed by Provider Intelligence through `catalog_storage`, not by Interface Manager.

## 6. Provisional logical storage and access matrix

This matrix defines intended ownership and safe access boundaries. It is **not** a grant system and does not claim that Phase 5 authorization is implemented.

Legend:
- **R** = read through owning service/repository.
- **W** = write through owning service/repository.
- **—** = no direct access.
- **Policy hook** = request an authorized, scoped result; default deny until a later Permission Manager authorizes it.

| Module / actor | Conversations | Profile | Provider catalog & observations | Runtime state/events | Memory | Context package | Knowledge metadata/files |
|---|---:|---:|---:|---:|---:|---:|---:|
| Conversation Processing (planned boundary) | R/W | R (minimum fields only) | R via Interface Manager | R via Runtime Manager snapshot | R via Memory Service | W/assemble | Policy hook |
| Interface Manager | — | — | R via catalog service/contract only (target); current implementation reads version-controlled operator manifests and provider capabilities, not persisted catalog tables | — | — | — | — |
| Provider Intelligence service | — | — | R/W through Catalog/Provider Observation repositories | R only through Runtime Manager result contracts when needed | — | — | — |\n| Local Model Runtime | — | — | — | R/W via Runtime Repository | — | — | — |
| Profile service (current route behavior; target service planned) | — | R/W | — | — | — | — | — |
| Memory Service (planned) | R only through conversation contract when provenance/source is needed | — | — | — | R/W | — | Policy hook |
| Context Manager (planned) | R via Conversation service | — | — | — | R via Memory service | W/request-scoped only | Policy hook |
| Knowledge Storage (planned) | — | — | — | — | — | — | R/W within owned domain |
| AI Librarian (Phase 10) | — | — | — | — | — | Policy hook | R/W in private workspace; publish only after explicit approval |
| Supervisor / specialized agents (Phases 6–9) | Policy hook | — | R only through approved capability summaries | R only through approved runtime service | Policy hook | R only for assigned task scope | Policy hook |
| Tool Runtime / Permission Manager (Phase 5) | Policy-mediated | Policy-mediated | Policy-mediated | Policy-mediated | Policy-mediated | Policy-mediated | Policy-mediated |
| External model/provider | — by default | — | Only provider request data explicitly selected for transmission | — | — | Only explicitly approved, minimized prompt context | — by default |

### 6.1 Agent-specific default-deny rules

- No agent exists in the current implementation with a database credential, SQLAlchemy session, or direct table grant.
- Future agents must not receive `Session`, `SessionLocal`, engine handles, raw SQL capability, or arbitrary repository objects.
- A model response or agent plan cannot create or expand its own permissions.
- An agent receives only a typed task context and explicitly exposed service/tool capabilities.
- Memory retrieval is not authorization. A memory record cannot grant access to its source file, conversation, connector, or another memory scope.
- Private local context must never be sent to an external provider through implicit fallback.
- Cross-domain reads and all destructive/external actions remain default-deny until Phase 5 supplies the policy decision and audit boundary.

## 7. Draft storage contracts for review

These are contract requirements, not implementation claims.

### 7.1 Storage Manager

- Own database configuration, backend adapter selection, engine lifecycle, session factory, transaction/unit-of-work lifecycle, health/readiness, and normalized storage exceptions.
- Expose narrow session/unit-of-work factories to repositories; do not expose engine/session handles to routes, agents, or model-facing code.
- SQLite is the required backend for this phase. A future PostgreSQL adapter must conform to the same contract but is not required to be deployed.
- Support isolated temporary database fixtures for tests.
- Own connection policy and migration startup sequencing.

### 7.2 Repository

- One repository owns one logical domain or a clearly bounded aggregate.
- Expose typed domain operations, not arbitrary SQL or unrestricted query builders.
- Keep SQLAlchemy models and sessions inside persistence adapters where practical.
- Make transaction ownership explicit: either the application unit of work commits once, or a documented standalone repository operation owns its transaction. Do not mix both implicitly.
- Never mutate another domain's tables to implement a convenience feature.
- Provide deterministic contract and integration tests.

### 7.3 Conversation Storage

- Own `sessions` and `messages` without replacing their existing identities.
- Expose create, retrieve, append, ordered history, pagination, rename/archive, and policy-controlled deletion operations as required by existing behavior.
- Preserve timestamps, roles, message content, model/provider provenance where available, custom title behavior, and existing user history.
- Do not expose arbitrary cross-session search without an explicit scope/policy contract.

### 7.4 Memory Service

- Own memory records, scopes, provenance, confidence/evidence state, retention, lifecycle, and retrieval.
- Distinguish candidate AI-derived memories from user-provided or user-approved facts.
- Support create/read/update/supersede/expire/delete through typed operations.
- Must not store credentials or grant permissions.
- Must not silently promote model output into authoritative long-term memory.

### 7.5 Context Manager

- Build request-scoped typed context from authorized service results.
- Preserve provenance, scope, freshness/unknown status, and source references.
- Apply relevance ranking, deduplication, and explicit token/size budgets.
- Never broaden scope because a retrieval result appears relevant.
- Never persist a second shadow copy of all conversation/memory data.

### 7.6 Knowledge and File Storage

- Separate original source files, source metadata, extracted text, chunks, indexes, embeddings, AI-derived artifacts, and approved knowledge.
- Keep original files outside database BLOB storage by default; use validated opaque identifiers and managed references.
- Expose file operations through a managed adapter; never accept arbitrary model-supplied filesystem paths.
- Keep lexical search replaceable; SQLite FTS5 is a candidate only after runtime compatibility and test validation.
- Publication into Approved Knowledge requires a later explicit review/approval workflow.

### 7.7 Permission integration seam

Phase 4 must provide scope/policy hooks and safe default-deny behavior for protected reads. It must not implement a parallel permission database or attempt to complete Phase 5's Permission Manager. The authoritative permission model remains the Phase 5 contract.


## 8. Initial migration and compatibility risk register

| Risk | Evidence / impact | Required mitigation before schema changes |
|---|---|---|
| Existing user data loss | One SQLite file stores chat, profile, catalogs, and runtime state | Work only on disposable copies; inventory real schema and record counts; preserve stable IDs |
| Unversioned schema history | `create_all()` plus two inline ALTER checks | Baseline actual deployed schemas; choose migration tool only after validating startup and legacy DB behavior |
| Session/message relationship ambiguity | ORM cascade but nullable FK/default DB cascade behavior | Inspect actual SQLite DDL and PRAGMA settings; test ORM and direct DB deletion behavior |
| Transaction boundary mismatch | Catalog functions commit internally; runtime repository owns sessions; routes commit directly | Define unit-of-work ownership and add rollback/atomicity tests |
| SQLite locking/concurrency | Current connection options do not document busy timeout/journal policy | Reproduce under tests; tune only with evidence and avoid heavy tests on constrained hardware |
| Avatar BLOB coupling | Profile image bytes reside in `user_profile` | Preserve in initial migration; consider managed file storage only as a separately tested migration |
| JSON payload drift | Provider/runtime JSON fields are flexible and weakly versioned | Document payload schemas/versioning and redaction before cross-module reuse |
| Startup coupling | Import/startup calls DB init and catalog seed | Preserve externally visible startup semantics; add isolated app/database fixtures |
| Future agent overreach | No current agent runtime or Permission Manager exists | Do not grant DB/session access; keep typed service contracts and default-deny policy hooks |

### 8.1 Repository gap analysis and planned change map

This is a preliminary file-level change forecast, not authorization to modify every listed file at once. Work-package boundaries in `PHASE_04_EXECUTION_PLAN.md` remain controlling.

| Existing file | Current responsibility / gap | Planned treatment | Earliest WP |
|---|---|---|---|
| `core/database.py` | ORM models, global engine/session factory, SQLite path creation, schema initialization and inline ALTERs coexist in one module | Retain model definitions during transition; move engine/session/migration lifecycle behind Storage Manager; keep a temporary compatibility facade until all callers migrate | 4.2 |
| `main.py` | Application startup, global session factory use, request dependency, direct Profile/Conversation ORM operations, catalog orchestration | Replace startup/session wiring with Storage Manager dependency; move Profile/Conversation operations to services incrementally; preserve API payloads and stream persistence behavior | 4.2–4.4 |
| `core/catalog_storage.py` | Domain persistence is centralized by table family, but accepts raw Session and commits internally | Wrap/adapt behind Catalog and Provider Observation repositories; normalize unit-of-work ownership only with characterization tests | 4.3 |
| `core/provider_intelligence.py` | Provider/runtime orchestration receives raw Session and invokes several independently committing storage functions | Inject domain repository/service interfaces; preserve separation between process control and DB persistence | 4.3 |
| `core/runtime/repository.py` | Runtime persistence adapter owns raw session creation and transaction | Retain behavior; inject Storage Manager-owned unit of work/session factory and keep ORM confined to adapter | 4.2–4.3 |
| `core/runtime/factory.py` | Composition root injects raw session factory into RuntimeRepository | Change injection to Storage Manager/repository factory while keeping the runtime manager ORM-free | 4.2–4.3 |
| `core/interface_manager.py` | Provider-neutral interface; no direct SQLAlchemy access | Retain ORM-free; only consume catalog service contracts if persistent catalog data is needed | 4.3 |
| `core/runtime/manager.py`, `monitor.py` | Runtime orchestration/monitoring; no DB access observed | Retain ORM-free; do not add SQLAlchemy | 4.3 |
| `core/orchestrator.py` and `core/providers/*` | Model/provider selection and adapter invocation; no DB access observed | Retain ORM-free | No planned persistence change |
| `tests/test_catalog_storage.py` | Catalog persistence characterization and legacy additive-column migration test | Extend to repository contract, transaction ownership, and migration compatibility | 4.2–4.3, 4.7 |
| `tests/test_runtime_manager.py` | Runtime manager and RuntimeRepository persistence behavior | Retain and extend to Storage Manager injection and rollback behavior | 4.2–4.3 |
| `tests/test_provider_intelligence.py` | Provider intelligence orchestration using in-memory SQLite fixtures | Preserve workflow assertions and adapt fixture wiring as repositories are introduced | 4.3 |
| New `core/storage/*` | Not present | Add Storage Manager, SQLite adapter, config, session/unit-of-work helpers and normalized exceptions; avoid empty future placeholders | 4.2 |
| New `core/repositories/*` | Not present | Add typed repositories incrementally for Profile, Conversation, Catalog, Runtime, Memory and Knowledge | 4.3 onward |
| New `core/conversations/*` | Not present | Add conversation service and typed schemas; preserve existing tables and API behavior | 4.4 |
| New `core/memory/*`, `core/context/*`, `core/knowledge/*` | Not present | Implement only when each package's data contract and scope rules are accepted; no speculative tables | 4.5–4.7 |

### 8.2 Confirmed schema constraints and unresolved database facts

- The ORM declares 14 tables in the current shared metadata: `sessions`, `messages`, `user_profile`, `operator_catalogs`, `operator_model_profiles`, `live_model_catalog`, `provider_runtime_status`, `model_runtime_status`, `provider_quota_snapshots`, `catalog_sync_history`, `provider_intelligence_reports`, `runtime_model_states`, `runtime_statuses`, and `runtime_events`.
- `messages.session_id` is nullable by ORM default and references `sessions.id`; no `ondelete` action is declared. The relationship's `delete-orphan` cascade is an ORM behavior, not proof of SQLite foreign-key enforcement.
- The SQLite adapter currently does not explicitly set `PRAGMA foreign_keys=ON`, busy timeout, or journal mode. These remain deliberate follow-up configuration decisions; do not assume enforcement based on ORM declarations alone.
- Several tables have explicit indexed columns through `index=True` (for example session/message IDs, provider IDs on history/snapshots/reports, and runtime event lookup/time columns). Composite primary keys exist for provider/model profiles, live models, model runtime status, and runtime model state.
- The test fixtures create independent in-memory engines and call `Base.metadata.create_all()`; those test engines are not additional production engine ownership sites.
- The current source audit establishes the authoritative ORM-declared schema. The exact contents of the user's local `data/chat_history.db` are intentionally not inspected because the user has confirmed that its test data may be discarded and no compatibility migration is required.

## 9. Decisions already supported by project documents

1. One local SQLite operational database is the current baseline; logical domains share it unless a measured requirement justifies physical separation.
2. PostgreSQL is a future adapter/hosting target, not a Phase 4 deployment requirement.
3. Repository boundaries separate domain logic from SQLAlchemy and database dialects.
4. Existing `core/database.py`, `core/catalog_storage.py`, and `core/runtime/repository.py` are compatibility anchors until callers and tests are migrated.
5. Memory and request Context are separate services and separate concepts.
6. Phase 4 supplies permission hooks only; full Tool Runtime and Permission Manager belong to Phase 5.
7. No speculative tables should be created before the owning workflow and contract are accepted.
8. WP-4.1 contracts are accepted as the working baseline for implementation; revise them only when code evidence or a concrete product requirement requires it.
9. Existing local database rows are disposable test data. A clean database initialization is sufficient; no legacy-row migration or backup gate is required.

## 10. WP-4.1 exit review

- [x] Inventory all 14 ORM-declared tables and classify their logical owners.
- [x] Inspect the principal production engine/session lifecycle, request-scoped sessions, catalog writes, provider-intelligence workflow, and runtime repository.
- [x] Review transaction ownership and the current commit/rollback behavior that must be preserved or deliberately changed.
- [x] Establish the initial storage ownership and module access matrices.
- [x] Define working contracts for Storage Manager, repositories, Conversation, Memory, Context, Knowledge, and managed files.
- [x] Record the main implementation touch points and cross-phase boundaries.
- [x] Confirm the user's data-retention decision: current SQLite rows are disposable test data; a clean schema is acceptable and no backup or legacy-row migration is required.
- [x] Accept ORM metadata and isolated in-memory test databases as the schema baseline; direct inspection of the user's local DB file is not a prerequisite.

**WP-4.1 outcome:** complete for the current project baseline. This is a working approval to proceed with WP-4.2. It does not approve speculative Memory/Knowledge schemas, full Phase 5 permissions, or later work packages before their own contracts and tests.

## 11. WP-4.2 implementation snapshot

The first Storage Manager increment is committed on `feat/storage-memory-services`:

- `core/storage/config.py`: environment-backed database URL/path and SQL echo configuration.
- `core/storage/adapters/base.py` and `sqlite.py`: backend adapter contract and active SQLite engine adapter.
- `core/storage/manager.py`: centralized engine/session-factory lifecycle, explicit session/transaction scopes, health check, and disposal.
- `core/storage/session.py`: close-safe session and transaction context managers; no implicit commit in a plain session scope.
- `core/storage/exceptions.py`: normalized storage exception types.
- `core/database.py`: ORM models remain in place; legacy `engine` and `SessionLocal` imports now delegate to the manager.
- `tests/test_storage_manager.py`: focused coverage for path creation, health check, transaction commit/rollback, in-memory SQLite, and unsupported backend rejection.

Configuration:
- `LOCAL_AI_DATABASE_URL` optionally overrides the database URL.
- `LOCAL_AI_DATABASE_PATH` overrides the default SQLite file path.
- `LOCAL_AI_SQL_ECHO` enables SQLAlchemy SQL logging when explicitly set to a truthy value.

**WP-4.2 status:** foundation implemented; local test execution and application smoke test are still required before its exit gate is approved. Existing callers continue to work through compatibility exports. Catalog transaction ownership and route-level ORM access are intentionally deferred to WP-4.3/WP-4.4.

## 12. Execution directive

**Project:** Local AI Assistant  
**Phase:** 4 of 11 — Storage & Memory Services  
**Work package:** WP-4.1 — Storage Audit & Contracts

**Mandatory instruction:** Treat this audit as the accepted working baseline for Local AI Assistant, Phase 4, WP-4.1. Proceed with WP-4.2 and keep the implementation incremental. Existing Phase 2/3 application behavior must remain functional, but preservation of the current disposable SQLite test rows is not required. Do not create speculative Memory/Knowledge tables and do not implement Phase 5 authorization in parallel.
