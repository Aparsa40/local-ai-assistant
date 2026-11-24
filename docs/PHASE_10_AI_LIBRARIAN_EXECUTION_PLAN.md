# Phase 10 — AI Librarian

**Project:** Local AI Assistant  
**Phase:** 10 of 11  
**Document type:** Authoritative execution plan  
**Status:** Planned — execution contract prepared; no AI Librarian workflow is claimed  
**Dependencies:** Phase 4 Knowledge Storage, Phase 5 permissions/approvals, Phases 6–9 agent execution  
**Last reviewed:** 2026-11-24

## 1. Purpose and boundary

Build a user-controlled workflow that registers and ingests sources, extracts and classifies material, detects changes/conflicts, generates traceable reports, and proposes knowledge for review. The Librarian Workspace is private working material. Approved Knowledge is a separate publication state requiring explicit validation and user approval.

Knowledge Storage in Phase 4 provides metadata, managed files, extracted artifacts, chunks, and SQLite FTS5 search; it does not itself perform automatic ingestion or publication.

## 2. Current baseline and reuse

Reuse `core/knowledge/`, `core/repositories/knowledge_repository.py`, `core/context/`, `core/permissions/`, `core/tools/runtime.py`, Agent Runtime, and the approved handoff/validation services from earlier phases. Do not create a second source store or bypass source scopes.

## 3. Scope

- Explicit source registration and ingestion authorization.
- Safe file/document extraction adapters with format and size allowlists.
- URL ingestion only through a constrained fetch adapter with SSRF protections, redirect/DNS/IP checks, response limits, and explicit user authorization.
- Incremental change detection by content hash/version.
- Classification, chunking, cross-reference, deduplication, and conflict detection.
- Librarian workspace artifacts and provenance.
- Evidence coverage reports and review queue.
- Approved Knowledge publication with one-time action-bound approval.
- Separate retrieval knowledge from training dataset preparation.

Out of scope: automatic publication, silent crawling, arbitrary filesystem access, unrestricted URL fetch, treating model summaries as verified facts, and model training in this phase.

## 4. Work packages

### WP-10.1 — Source and ingestion policy
Define supported source types, scope, owner, allowed formats, maximum sizes, retention, destination, and authorization checks. Reject path traversal, unsupported MIME, credential-bearing URLs, private-network targets, and unbounded redirects.
**Exit:** no ingestion starts without explicit owner permission and a bounded source descriptor.

### WP-10.2 — Extraction adapters
Implement deterministic extractors for an initially small allowlist (plain text, Markdown, HTML, PDF, and selected Office formats only when safe libraries are available). Normalize encoding and preserve page/section/offset locators. Isolate parser failures and enforce CPU/memory/time limits.
**Exit:** extraction yields versioned text plus extractor/version provenance, or a normalized failure; original files remain unchanged.

### WP-10.3 — Change detection and indexing
Compare source hashes and metadata versions; avoid reprocessing unchanged files. Index chunks through KnowledgeService and keep prior artifacts/history. Rebuild FTS safely after migration/repair. Add extraction and indexing idempotency.
**Exit:** repeated ingestion of unchanged content does not duplicate artifacts or corrupt the active index.

### WP-10.4 — Classification and cross-reference
Use deterministic metadata first and bounded model assistance only for candidate labels/relationships. Validate model output schema and cite exact source/chunk IDs. Detect exact duplicates and flag semantic conflicts for review.
**Exit:** every classification and relationship has provenance and an unreviewed/verified state.

### WP-10.5 — Librarian analysis and reports
Generate reports with scope, source inventory, coverage, extraction errors, claims, citations, contradictions, and unresolved gaps. Do not present generated summaries as facts without source links.
**Exit:** report claims are traceable to stored source chunks and can be independently reviewed.

### WP-10.6 — Review and publication
1. Build a private review queue.
2. Allow accept/reject/edit decisions by the local owner.
3. Require action-bound ApprovalService approval for publication.
4. Publish only selected validated artifacts into an explicitly defined Approved Knowledge collection.
5. Record publisher, approval ID, source versions, and audit event.
6. Support unpublish/revoke and stale-source invalidation.
**Exit:** no AI artifact becomes Approved Knowledge without explicit approval.

### WP-10.7 — UI, permissions, and regression
Add source management, ingestion progress, review queue, report viewer, and publication history. Test malicious files, zip bombs, SSRF, path traversal, prompt injection, secrets, scope isolation, hash changes, extraction errors, and approval replay.
**Exit:** user can inspect every source and approve every publication decision.

### WP-10.8 — Documentation and delivery
Update Knowledge Storage, Librarian, security, architecture, roadmap, and API docs. Deliver one phase PR after CI and migration tests pass.

## 5. Suggested implementation map

```text
core/librarian/
  sources.py
  extractors/
  ingestion.py
  classifier.py
  cross_reference.py
  reports.py
  review.py
  publication.py
core/knowledge/
  # existing Phase 4 storage/retrieval boundary
core/repositories/
tests/
  test_librarian_ingestion.py
  test_extractors.py
  test_ssrf_guards.py
  test_librarian_reports.py
  test_knowledge_publication.py
```

## 6. Required validation

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

Add adversarial parser/URL tests and temporary managed-file fixtures. Never test URL ingestion against arbitrary private network resources. No live model is required for parser/security CI; use fake model responses.

## 7. Phase-wide acceptance

- Ingestion is explicit, scoped, bounded, and auditable.
- Original files and extracted artifacts remain distinct and versioned.
- Re-ingestion is idempotent and incremental.
- Every claim/classification/report is traceable to source chunks.
- Conflicts and missing coverage remain visible.
- Private Librarian Workspace is separate from Approved Knowledge.
- Publication requires explicit one-time approval and can be revoked.
- No untrusted file or URL can access arbitrary paths or internal networks.
- Tests, migrations, documentation, and CI evidence pass.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 10 of 11 — AI Librarian

Execute WP-10.1 through WP-10.8 in order. Preserve the Phase 4 Knowledge contracts and Phase 5 authorization boundary. Do not equate successful extraction or model-generated summary with approval or factual verification.
