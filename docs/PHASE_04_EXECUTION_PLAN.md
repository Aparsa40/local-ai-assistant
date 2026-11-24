# Phase 4 — Storage & Memory Services

**Project:** Local AI Assistant  
**Phase:** 4 of 11  
**Document type:** Authoritative execution plan  
**Status:** Partially complete — WP-4.1 through WP-4.6 implemented and validated; WP-4.7 Knowledge Storage & Migration remains pending  
**Execution branches:** `feat/storage-memory-services` (WP-4.1–WP-4.4), `feat/phase-4-memory-service` (WP-4.5; stacked PR), and `feat/phase-4-context-manager` (WP-4.6; stacked PR)  
**Last reviewed:** 2026-11-24

## 1. Purpose

Build a coherent, durable, and provider-neutral data foundation for the next agentic phases. This phase consolidates the existing SQLite/SQLAlchemy persistence, introduces stable Storage and Repository boundaries, completes conversation persistence services, and adds independent Memory, Context, and Knowledge Storage services.

This phase is an extension of the existing system, not a wholesale database rewrite. Existing sessions, messages, profile, catalog, and runtime functionality must continue to work. The user has confirmed that current local database rows are disposable test data; preserving those rows or migrating them into the new schema is not required. A clean database may be initialized as part of the implementation.

**Core distinction:**
- Storage is responsible for durable persistence and managed file access.
- Repository Services provide domain-owned data access.
- Memory Service manages information retained for future use.
- Context Manager selects information needed for one specific request.
- Knowledge Storage manages source metadata and derived knowledge artifacts.
- Migration & Persistence controls schema evolution and data safety.

A database table by itself is not a Memory system, and Memory is not the same thing as request Context.

## 2. Phase objectives

1. Establish a single, documented Storage Manager boundary.
2. Standardize repository access without leaking ORM/session details into application services.
3. Preserve and complete conversation/session/message persistence.
4. Introduce a controlled Memory lifecycle with provenance, retention, and retrieval.
5. Introduce Context assembly with relevance, token budgets, and access checks.
6. Establish Knowledge Storage metadata and source/derived-artifact separation.
7. Introduce repeatable, versioned migrations for the accepted clean schema baseline; migration of pre-Phase-4 test rows is not required.
8. Keep the design compatible with a future PostgreSQL adapter without requiring PostgreSQL deployment in this phase.
9. Provide tests and integration seams required by Tool Runtime, Agent Runtime, Conversation Agent, and AI Librarian phases.

## 3. Scope and boundaries

### In scope

- Storage Manager and database adapter contracts.
- SQLite as the operational local backend.
- SQLAlchemy integration behind storage/repository boundaries.
- Repository contracts and domain repositories.
- Conversation and message persistence service.
- Short-term, long-term, episodic, and semantic memory categories.
- Memory provenance, lifecycle, retrieval, ranking, and retention policies.
- Context assembly, relevance ranking, deduplication, access filtering, and token budgeting.
- Knowledge source metadata, file references, extracted-text/chunk metadata, lexical search foundation, and provenance.
- Managed file-storage abstraction and safe metadata association.
- Versioned schema migrations and migration testing.
- Backward-compatible integration with current catalog/runtime persistence.

### Explicitly out of scope

- Full Tool Runtime and Permission Manager implementation (Phase 5). Phase 4 must expose policy hooks and default-deny integration points, not invent a parallel permission system.
- Agent Runtime, Supervisor, Conversation Agent, or Multi-Agent execution (Phases 6–9).
- Full AI Librarian ingestion, analysis, report review, or publication workflow (Phase 10).
- Complete backup/restore and maintenance scheduler (Phase 11).
- Mandatory PostgreSQL deployment or production migration.
- Mandatory vector database, hosted embedding service, or large external search stack.
- Automatic ingestion of arbitrary user files.
- Automatic publication of AI-generated memory or knowledge as trusted facts.

## 4. Architecture and ownership

### 4.1 Storage Manager

Owns:
- database engine/connection configuration;
- session and transaction lifecycle;
- adapter selection;
- storage-specific exception normalization;
- health/readiness information for persistence;
- managed file-storage adapter registration.

Must not own:
- conversation business rules;
- memory ranking or retention decisions;
- context relevance decisions;
- knowledge approval;
- permission grants.

SQLite is the only required operational adapter in this phase. Define a backend-neutral contract so PostgreSQL can be introduced later without rewriting domain services. Do not claim PostgreSQL support is complete merely because an interface exists.

### 4.2 Repository Services

Each repository owns access to one domain's records. Repositories must:
- expose domain-oriented operations rather than arbitrary SQL execution;
- keep SQLAlchemy sessions and ORM entities behind the persistence boundary where practical;
- use explicit transaction boundaries;
- support deterministic tests;
- avoid direct mutation of another domain's tables.

Existing `core/catalog_storage.py` and `core/runtime/repository.py` must be audited first. Preserve their semantics and migrate them incrementally; do not replace them wholesale without compatibility tests.

### 4.3 Conversation Storage

Owns conversation/session/message persistence:
- create and retrieve sessions;
- append and retrieve messages in stable order;
- preserve role, timestamp, model/provider metadata, and safe message metadata where supported;
- paginate long histories;
- rename/archive/delete according to explicit policy;
- preserve existing startup behavior and existing user data.

The current `sessions` and `messages` tables are the starting point. Do not create duplicate conversation tables simply to match a new naming convention.

### 4.4 Memory Service

Memory records must include, as applicable:
- stable memory ID;
- memory type;
- content or structured payload;
- source/provenance reference;
- creation and update timestamps;
- confidence/evidence status where applicable;
- importance and freshness signals;
- scope/owner;
- retention or expiry policy;
- lifecycle status (for example candidate, active, superseded, expired, or deleted).

Initial logical memory categories:

| Category | Purpose | Typical lifetime |
|---|---|---|
| Short-term | Working facts for the active conversation/task | Session or bounded task |
| Long-term | Stable preferences or durable facts approved for retention | Until superseded or removed |
| Episodic | Specific events, decisions, and outcomes | Retained by policy |
| Semantic | Normalized concepts and relationships | Retained while valid |

Procedural memory is deliberately deferred until the system has a clear workflow for storing and validating reusable procedures. It must not be mixed with tool definitions or permission grants.

Memory Service responsibilities:
- create and validate candidate memory records;
- deduplicate or identify conflicting records;
- retrieve memories by scope and relevance;
- rank by relevance, freshness, importance, and confidence;
- update, supersede, expire, or delete records;
- retain provenance and distinguish user-provided facts from AI-derived candidates;
- prevent unreviewed model output from silently becoming authoritative long-term memory.

Memory must not grant access to files, tools, connectors, or other data. Protected reads remain subject to the Permission Manager introduced in Phase 5.

### 4.5 Context Manager

Context is the request-scoped selection of information, not a second persistent memory store.

Context Manager responsibilities:
- receive a request/conversation/task scope;
- retrieve relevant conversation history;
- query Memory Service for eligible memories;
- query Knowledge Storage only through authorized interfaces;
- filter by scope and policy;
- rank and deduplicate candidate context;
- enforce token/size budgets;
- preserve source references and provenance;
- return a typed, explainable context package.

It must not:
- invent missing facts;
- silently broaden access scope;
- send private local context to a cloud provider;
- treat a retrieval match as proof that a fact is current or correct.

### 4.6 Knowledge Storage

Knowledge Storage manages metadata and references for sources and derived artifacts. It must keep the following distinct:

1. Original source file.
2. Source metadata and content hash.
3. Extracted text.
4. Chunks/segments and source locators.
5. Search indexes.
6. Embeddings/vector representations, if later enabled.
7. AI-generated summaries or reports.
8. Approved knowledge, which requires a later approval workflow.

Initial implementation should prioritize metadata, provenance, source versioning, file references, and lexical retrieval. SQLite FTS5 may be used as the initial lexical search backend after compatibility and performance checks. Vector retrieval must remain behind a replaceable adapter and is not a mandatory deliverable of this phase.

The complete document ingestion and AI Librarian workflow belongs to Phase 10.

### 4.7 Migration & Persistence

Migration responsibilities:
- introduce a versioned migration mechanism;
- identify and baseline existing SQLite schemas safely;
- apply ordered, repeatable migrations;
- record the current schema revision;
- define upgrade and downgrade behavior where safe;
- test migration from a copy of a representative existing database;
- preserve existing records and stable IDs;
- provide rollback/backup guidance before risky schema changes.

Alembic is the preferred candidate because the project uses SQLAlchemy, but adoption must be validated against the actual current schema and startup lifecycle before it is finalized.

Do not rely on `Base.metadata.create_all()` as the only schema evolution mechanism. It can create missing tables but does not provide a complete versioned migration history for existing tables.

## 5. Work packages and exact execution order

### WP-4.1 — Storage Audit & Contracts

**Goal:** understand the current persistence topology before changing it.

Tasks:
1. Inventory all SQLAlchemy models and database tables.
2. Trace every database engine/session creation site.
3. Find direct SQL, ORM queries, commits, rollbacks, and session lifecycle handling.
4. Map all callers of `core/database.py`, `core/catalog_storage.py`, and `core/runtime/repository.py`.
5. Identify data ownership, foreign keys, cascade behavior, and implicit transaction boundaries.
6. Inspect ORM metadata and test-created SQLite schemas; inspect the user's live database file only if a future concrete requirement needs it.
7. Define Storage Manager, Repository, Conversation, Memory, Context, Knowledge, and File Storage contracts.
8. Record migration risks and a backward-compatibility plan.

**Deliverables:**
- storage inventory and dependency map;
- current schema/data ownership map;
- repository gap analysis;
- accepted service contracts;
- migration and compatibility plan;
- explicit list of files/modules expected to change in later work packages.

**Exit gate:** no schema or storage refactor begins until this audit is reviewed and contracts are accepted.

### WP-4.2 — Storage Manager

**Goal:** establish one controlled persistence lifecycle.

Tasks:
1. Implement centralized configuration for database URL/path and backend selection.
2. Centralize engine creation and session factory lifecycle.
3. Define transaction/context-manager behavior and normalized storage exceptions.
4. Support SQLite connection settings and safe local path creation.
5. Define a backend adapter contract for future PostgreSQL support.
6. Provide deterministic test fixtures and isolated temporary databases.
7. Preserve current application startup and dependency injection behavior.

**Deliverables:** Storage Manager, SQLite adapter, session/transaction helpers, storage configuration, and focused tests.

**Exit gate:** Storage Manager is wired into application startup and request-scoped sessions. Validation passed on 2026-11-24: 6 focused Storage Manager tests, 115 total tests, and `compileall`. A separate live HTTP startup smoke test remains unrecorded.

### WP-4.3 — Repository Services

**Goal:** standardize domain data access.

**Validated implementation status (2026-11-24):** Catalog, runtime, profile, session, and message repository modules are implemented. Catalog persistence logic is behind `CatalogRepository`; `core/catalog_storage.py` remains a compatibility facade. The runtime repository implementation is in `core/repositories/runtime_repository.py`, with its previous import path retained. Validation completed: 59 focused repository tests and 120 total tests passed; `python -m compileall -q core main.py` passed. Profile/session/message API routes were subsequently migrated in WP-4.4.

Tasks:
1. Define the repository base/protocol and transaction conventions.
2. Implement or adapt repositories for sessions, messages, profiles, catalogs, and runtime records.
3. Add repositories for memory and knowledge records when their schemas are approved.
4. Move query/commit logic out of route handlers and unrelated services.
5. Preserve existing catalog sync safety rules and runtime event semantics.
6. Prohibit uncontrolled cross-domain table mutation.
7. Add repository contract and integration tests.

**Deliverables:** documented repository contracts and domain-specific repositories.

**Exit gate:** migrated callers no longer depend on another domain's ORM tables or manually manage unrelated sessions.

### WP-4.4 — Conversation Storage

**Goal:** provide a stable service for conversation history.

Tasks:
1. Audit current session/message creation and startup behavior.
2. Define conversation/message schemas and service operations.
3. Implement create, append, fetch, paginate, rename/archive, and policy-controlled delete operations as required by existing product behavior.
4. Preserve role, ordering, timestamps, model/provider provenance, and title customization behavior.
5. Integrate the existing UI/API paths through Conversation Storage.
6. Add regression tests for fresh-chat behavior and historical conversation retrieval.

**Deliverables:** Conversation Storage service, typed schemas, repository integration, and API/UI regression coverage.

**Exit gate:** existing conversations remain readable and current chat behavior is unchanged.

**WP-4.4 implementation status (2026-11-24):** ConversationService and ProfileService are implemented on `feat/storage-memory-services`. Session, message, profile, and avatar endpoints delegate domain operations to these services; route handlers retain HTTP translation and response transport only. Chat still commits the user turn before provider inference and persists the assistant turn only after a successful stream. Avatar normalization and existing validation limits remain in ProfileService. No schema or table changes were made. User-local validation passed: 13 focused service/API tests, 124 total tests, Python compilation, and frontend JavaScript syntax check.

### WP-4.5 — Memory Service

**Goal:** introduce durable, controlled application memory.

Tasks:
1. Define memory types, schemas, ownership scopes, provenance, and lifecycle states.
2. Define candidate creation and validation rules.
3. Implement create/read/update/supersede/expire/delete operations.
4. Implement deduplication and conflict detection at a conservative baseline.
5. Implement relevance retrieval and ranking using deterministic metadata first.
6. Add retention and freshness policies.
7. Ensure AI-generated candidate memories are not automatically treated as verified facts.
8. Add privacy/default-deny hooks for protected memory access.
9. Add tests for lifecycle, provenance, scope isolation, stale/conflicting records, and deletion.

**Deliverables:** Memory Service, Memory Repository, schemas, retrieval/ranking, lifecycle policies, and tests.

**Exit gate:** memory records are traceable, scoped, lifecycle-managed, and cannot grant permissions or silently promote unverified content.

**WP-4.5 implementation status (2026-11-24):** Memory Service is implemented on `feat/phase-4-memory-service`, stacked on `feat/storage-memory-services`. It adds the `memories` ORM table, owner- and scope-filtered `MemoryRepository`, typed contracts, default-deny access policy, deterministic retention/scoring, and lifecycle/retrieval operations. Candidate records require explicit reviewer activation; AI-generated records remain candidates. User-local validation passed: 13 focused Memory/Storage tests, 131 total tests, Python compilation, and frontend JavaScript syntax check. GitHub Actions also passed 131 tests and both syntax/compile checks. No vector/embedding service, API endpoint, Phase 5 permission system, or migration framework is included.

### WP-4.6 — Context Manager

**Goal:** assemble bounded and permission-aware request context.

Tasks:
1. Define a typed Context Package with source references and provenance.
2. Retrieve relevant recent conversation messages.
3. Retrieve eligible memories from Memory Service.
4. Add a Knowledge Storage retrieval adapter when the relevant WP-4.7 contract is ready.
5. Rank, deduplicate, and filter candidate context.
6. Implement token/size budget policies with conservative fallback behavior.
7. Preserve unknown/stale status rather than presenting it as fact.
8. Enforce scope checks and provide an integration hook for Phase 5 Permission Manager.
9. Add deterministic tests for ordering, budgets, deduplication, provenance, and access denial.

**Deliverables:** Context Manager, assembler, ranking, budget policy, typed context package, and tests.

**Exit gate:** a request receives only the context allowed for its scope and budget, with traceable sources.

**WP-4.6 implementation status (2026-11-24):** Context Manager implementation is complete on `feat/phase-4-context-manager` and merged to `main` through Phase 4 PR #10. Added typed request/item/package contracts, bounded chronological conversation retrieval, explicit memory-scope retrieval through MemoryService, deterministic cross-source ranking and deduplication, provenance preservation, and a conservative character-based token budget. Knowledge retrieval remains disconnected until WP-4.7; Phase 5 permissions are not implemented here. The final Phase 4 main-branch CI passed 137 tests, Python compilation, and frontend syntax validation; the user also confirmed 23 focused local tests and 137 full-suite tests passed.

### WP-4.7 — Knowledge Storage & Migration

**Goal:** provide a durable foundation for source metadata and safe schema evolution.

Tasks:
1. Define source, file reference, extracted artifact, chunk, and index metadata schemas.
2. Keep original files outside database BLOB storage by default; store managed references and integrity metadata.
3. Define file adapter operations and safe path/identifier handling.
4. Implement metadata repositories and source hashing/version references.
5. Add lexical search foundation (SQLite FTS5 if supported by the current SQLite runtime and tests).
6. Keep vector/embedding storage behind a replaceable adapter; do not require an external vector service.
7. Introduce versioned migrations after baselining the existing schema.
8. Test fresh database creation and migration from a copy of a representative existing database.
9. Verify sessions, messages, profile, catalogs, runtime states, and runtime events are created and usable in a clean database.
10. Document backup/restore prerequisites for future Phase 11 work.

**Status:** Pending. No Knowledge Storage service, managed file adapter, lexical search foundation, or versioned migration framework is implemented yet.

**Deliverables:** Knowledge Storage metadata foundation, managed file adapter contract, lexical search baseline where accepted, migration history, migration tests, and data-preservation report.

**Exit gate:** migrations are repeatable and preserve existing records; source files and derived artifacts remain distinct and traceable.

## 6. Target package layout

This is the intended logical layout. Create modules incrementally when their work package begins; do not create empty placeholder files for every future component.

```text
core/
├── storage/
│   ├── manager.py
│   ├── config.py
│   ├── session.py
│   ├── exceptions.py
│   └── adapters/
│       ├── base.py
│       └── sqlite.py
├── repositories/
│   ├── base.py
│   ├── session_repository.py
│   ├── message_repository.py
│   ├── profile_repository.py
│   ├── catalog_repository.py
│   ├── runtime_repository.py
│   ├── memory_repository.py
│   └── knowledge_repository.py
├── conversations/
│   ├── service.py
│   ├── schemas.py
│   └── policies.py
├── memory/
│   ├── service.py
│   ├── types.py
│   ├── scoring.py
│   ├── lifecycle.py
│   ├── retrieval.py
│   └── policies.py
├── context/
│   ├── manager.py
│   ├── assembler.py
│   ├── ranking.py
│   ├── token_budget.py
│   └── schemas.py
└── knowledge/
    ├── service.py
    ├── schemas.py
    ├── metadata.py
    └── search/
```

The exact layout may be adjusted after WP-4.1. Existing `core/database.py`, `core/catalog_storage.py`, and `core/runtime/repository.py` remain compatibility anchors until their callers are migrated and tests prove the change safe.

## 7. Data and migration constraints

- SQLite remains the local operational database.
- PostgreSQL compatibility is an architectural target, not a deployment requirement for Phase 4.
- Domain services must not depend on SQLite-specific SQL where a repository/adapter can provide the behavior.
- Do not add speculative tables before the owning workflow and repository contract are accepted.
- Do not store large original files in database rows by default.
- Keep file paths, IDs, and source locators validated; never trust imported paths.
- Keep secrets and credentials out of memory, context, and knowledge records unless a dedicated approved secret-management design explicitly requires otherwise.
- Use UTC timestamps consistently and document serialization semantics.
- Destructive operations require explicit scope and safe transaction behavior.
- Migrations must be tested against temporary databases. The current local test database may be deleted and recreated; no backup or legacy-row migration is required.
- A clean database reset is permitted for this project baseline because the user has explicitly approved discarding the existing test data. Do not silently reset it; document when a reset is required.

## 8. Integration requirements

### Interface Manager (Phase 2)

- Existing catalog and operational-report reads/writes must continue to work.
- Catalog facts, provider runtime observations, quota snapshots, and inference availability retain separate meanings.
- Repository refactoring must preserve last-known-good catalog behavior.

### Local Model Runtime (Phase 3)

- Runtime status, model lifecycle state, and lifecycle events retain current semantics.
- Runtime polling must not create unbounded duplicate events.
- Runtime repository errors must not silently corrupt the last trustworthy observed state.
- No hardware-intensive model tests are required for Storage & Memory validation.

### Future phases

- Phase 5 will connect Permission Manager checks to conversation, memory, knowledge, file, and tool access.
- Phases 6–9 will use Context Manager and repositories for agent state and scoped task context.
- Phase 10 will use Knowledge Storage as the foundation for ingestion and AI Librarian workflows.
- Phase 11 will provide consistent backup/restore and maintenance policies over the persistent data domains.

## 9. Required validation

Run the repository's CI-equivalent checks:

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

Add focused tests for each work package. At minimum, the complete phase must cover:

- Storage Manager engine/session lifecycle and transaction rollback.
- SQLite isolation and temporary test databases.
- Repository CRUD, ownership boundaries, and stable identifiers.
- Conversation ordering, pagination, and fresh-database behavior.
- Memory type/scope/provenance/lifecycle/retrieval and conflict behavior.
- Context ranking, deduplication, token budgets, and access filtering.
- Knowledge metadata, file integrity references, and lexical search behavior if enabled.
- Fresh-database migration and schema-version assertions.
- Regression tests for Interface Manager and Local Model Runtime.
- Error handling without leaking credentials, file contents, or sensitive metadata.

Record exact test counts and any environment limitations. A passing unit suite does not prove PostgreSQL compatibility unless PostgreSQL integration tests are actually run.

## 10. Phase-wide acceptance criteria

Phase 4 is complete only when:

1. Storage Manager is the controlled persistence entry point for migrated application services.
2. Repository contracts are documented and domain ownership is enforced.
3. Conversation and profile features operate correctly through Conversation Storage on a clean database; preserving pre-phase test rows is not required.
4. Memory Service supports scoped, provenance-aware lifecycle and retrieval.
5. Context Manager produces bounded, traceable, policy-filtered context.
6. Knowledge Storage can preserve source metadata and derived-artifact relationships without replacing original files.
7. Schema migrations are versioned, repeatable, and tested against fresh temporary SQLite databases.
8. Existing catalog and runtime persistence behavior remains compatible.
9. Full test suite and frontend syntax checks pass.
10. Documentation, implementation status, and acceptance evidence agree.
11. No functionality assigned to Phases 5–11 is incorrectly marked complete.

## 11. Delivery protocol

- Perform WP-4.1 audit before creating or changing database schemas.
- Use a dedicated feature branch: `feat/storage-memory-services`.
- Deliver work in small commits aligned with work packages.
- Update module contracts and the documentation index as each service becomes implemented.
- Keep PRs unmerged until required checks pass and the user explicitly authorizes merge.
- Do not mark the whole phase complete when only Storage Manager or repositories are finished.
- Keep a phase completion record with commits, tests, migrations, and known limitations.

## 12. Execution directive

**Project:** Local AI Assistant  
**Phase:** 4 — Storage & Memory Services

**Mandatory instruction:** This execution plan must be followed precisely for Local AI Assistant, Phase 4, in the order and boundaries defined above. Begin with WP-4.1 (Storage Audit & Contracts); do not start schema refactoring or implementation before the audit and contracts are reviewed. Preserve the behavior of Phases 2 and 3. The current disposable test database may be reset with the user's approval already recorded; do not claim that its rows are migrated. Do not skip work packages, weaken tests, invent successful migration results, or mark this phase complete until every phase-wide acceptance criterion has verifiable evidence.
