# Knowledge Storage

**Project:** Local AI Assistant  
**Phase:** 4 — Storage & Memory Services  
**Work package:** WP-4.7 — Knowledge Storage & Migration  
**Status:** Implemented and merged via PR #16  
**Merge commit:** `923ad244d91425cca50a64b4c683f62aa53b7fc0`

## 1. Responsibility

Knowledge Storage owns source metadata, managed original-file references, extracted artifacts, chunk metadata, lexical retrieval, and provenance. It is distinct from Memory Service: a Knowledge source is not automatically a verified memory or approved fact.

The document describes the current SQLite implementation. It does not claim PostgreSQL support, automatic document ingestion, embedding generation, or AI Librarian publication.

## 2. Current modules

| Module | Responsibility |
|---|---|
| `core/knowledge/models.py` | ORM records for sources, files, chunks, and derived artifacts |
| `core/knowledge/service.py` | Scoped source lifecycle, file association, extracted text indexing, lexical search |
| `core/knowledge/storage.py` | Managed file storage with opaque storage keys and integrity checks |
| `core/repositories/knowledge_repository.py` | Domain-owned persistence operations |
| `core/context/manager.py` | Explicit Knowledge scope retrieval and bounded context inclusion |
| `core/migrations/runner.py` | Ordered schema revision runner and SQLite FTS5 setup/repair |

## 3. Data lifecycle

1. Register a source with explicit owner and scope.
2. Optionally store an original file in managed storage; the database stores a reference, filename, size, content hash, and source version.
3. An upstream extractor or user supplies extracted text explicitly.
4. The service stores a versioned `extracted_text` artifact with extractor provenance.
5. Text is divided into deterministic overlapping chunks.
6. SQLite FTS5 indexes the active chunks. Insert/update/delete triggers synchronize the lexical index.
7. Search returns chunk/source references and ranking metadata. Retrieval does not certify factual correctness.

Original files, extracted artifacts, active chunks, and search index rows are separate records. Re-indexing replaces the active chunk set while retaining earlier extracted artifacts.

## 4. Scope and security

Every operation requires a KnowledgeScope containing scope type, scope ID, and owner ID. The default policy is `DenyAllKnowledgeAccessPolicy`; callers must inject an explicit access policy. Scope matching includes all three fields.

Credential-like values in source metadata, URIs, and extracted text are rejected by screening rules. This screening is defense-in-depth, not a secret vault or a guarantee that all sensitive content can be detected.

**Phase 5 integration status:** the Knowledge service is not yet wired to the central PermissionManager in the current main snapshot. Do not expose it through an API, agent, or tool until a PermissionManager-backed adapter is injected and covered by allow/deny tests.

## 5. Schema migrations

Current ordered SQLite revisions:

| Revision | Purpose |
|---|---|
| `0001_legacy_additive_columns` | Additive compatibility columns for existing schema |
| `0002_knowledge_fts` | Knowledge tables and FTS5 virtual index/triggers |
| `0003_knowledge_file_versions` | Source version on managed file records |
| `0004_knowledge_fts_trigger_fix` | Safe FTS row deletion, trigger replacement, and index rebuild |

The migration runner records applied revisions and is idempotent. Fresh database bootstrap and legacy-row preservation are covered by tests. The ORM metadata bootstrap remains for other ORM-owned tables; it is not a substitute for ordered schema changes.

SQLite is the only implemented migration backend. PostgreSQL migrations and cross-database portability are future work.

## 6. Current limitations

- File extraction is explicit; there is no automatic PDF/Office/HTML extraction pipeline.
- No embedding generation or vector database.
- No Approved Knowledge publication lifecycle; artifacts remain unreviewed.
- No general connector ingestion.
- No public Knowledge API or production tool handler.
- PermissionManager adapter integration is a Phase 5 remaining task.
- Backup/restore of the database plus managed files belongs to Phase 11.

## 7. Validation evidence

The PR #16 head CI run passed 228 tests on Python 3.11, plus Python compilation and frontend JavaScript syntax validation. This is CI evidence on Ubuntu; it is not a separate Windows runtime smoke test.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 4 of 11 — Storage & Memory Services  
**Work package:** WP-4.7 — Knowledge Storage & Migration

This document records the implementation merged into `main`. Keep source provenance, explicit scopes, default-deny behavior, SQLite migration semantics, and the stated limitations intact. Do not mark automatic ingestion, vector retrieval, Approved Knowledge, PostgreSQL migrations, or Phase 5 authorization integration as implemented until each is independently delivered and tested.
