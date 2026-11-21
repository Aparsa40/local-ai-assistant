# Document Ingestion and AI Librarian

**Status:** Accepted target workflow; implementation is planned.

## 1. Purpose

Document Ingestion handles authorized source acquisition and extraction. AI Librarian analyzes the resulting working material and creates traceable reports. Neither component replaces or modifies original source files.

## 2. Source lifecycle

1. **Discovery:** identify a candidate source and its metadata without reading content beyond what the discovery permission allows.
2. **Permission:** obtain explicit Source Ingestion Permission for the source/dataset and operations.
3. **Snapshot:** record source identity, version/hash, size/type, timestamps, and provenance.
4. **Extraction:** validate file type/size and extract text/metadata using format-specific adapters.
5. **Normalization:** preserve page, section, paragraph, sheet, row, or line locators where possible.
6. **Change detection:** compare source hashes/metadata to prior snapshots and process only changed material when safe.
7. **Analysis:** send permitted extracted material to the Librarian workspace.
8. **Report validation:** check source coverage, references, duplicates, contradictions, and unsupported claims.
9. **User review:** present the exact report version and its sources.
10. **Publication:** publish to Approved Knowledge only after explicit user approval.

## 3. Supported formats

Initial planned formats may include TXT, Markdown, PDF, DOCX, and CSV/XLSX. Each format needs validation and a dedicated extraction adapter. Unsupported or encrypted/corrupt files must produce an explicit status, not silent partial success.

Do not promise perfect extraction for scanned PDFs, complex tables, images, or embedded media. OCR and specialized parsers may be separate capabilities.

## 4. Provenance requirements

Every source record should preserve as much of the following as applies:
- source_id and source type;
- project/dataset scope;
- original filename or external identifier;
- content hash/version;
- ingestion time and source modified time;
- extractor name/version;
- locator such as page, heading, paragraph, line, sheet, row, or chunk;
- permission grant reference;
- extraction status and coverage.

Every report claim should distinguish:
- directly supported source statement;
- model interpretation/inference;
- unresolved or conflicting evidence.

Include model, prompt, pipeline, and validation versions where applicable.

## 5. Librarian responsibilities

The Librarian may:
- classify and tag authorized material;
- detect duplicates and changes;
- identify topics and relationships;
- cross-reference sources;
- detect conflicts and knowledge gaps;
- produce source, dataset, topic, cross-reference, conflict, change, and archive reports;
- validate report coverage and references.

It must not:
- ingest sources without permission;
- change or delete original source files;
- treat its own output as ground truth;
- publish to Approved Knowledge without user approval;
- automatically convert RAG content into a training dataset.

## 6. Incremental and periodic analysis

- **Incremental Analysis:** process new or changed authorized sources and compare them with existing approved knowledge.
- **Periodic Archive Review:** re-evaluate a selected authorized domain/archive to identify stale references, conflicts, duplication, and gaps.

The user selects the source scope and schedule. Periodic review does not create blanket permission to read newly added files outside the granted scope.

## 7. Storage states

Working extraction and draft artifacts belong to Librarian Workspace. Validated reports awaiting a user decision belong to Review & Approval. Only approved versions belong to Approved Knowledge.

Original files remain in independent file storage. Derived chunks and indexes can be regenerated according to policy but must not replace the source.

Related: [PERMISSIONS.md](PERMISSIONS.md), [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md), [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).
