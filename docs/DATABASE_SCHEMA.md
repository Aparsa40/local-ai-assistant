# Database and Repository Architecture

**Status:** Accepted storage direction; detailed schema is introduced incrementally.

## 1. Database strategy

- SQLite is the local-first database target.
- PostgreSQL is the hosted/online deployment target.
- Schema changes are migration-based.
- Domain modules access persistent records through repositories/data-access services.
- Logical data domains do not require separate physical databases.
- Original files are stored independently from database records.

The goal is portability and clear ownership, not premature abstraction or a large speculative schema.

## 2. Repository boundary

- Domain logic must not depend directly on raw SQL or a specific database engine.
- Repositories own persistence operations for their domain.
- Cross-domain access uses documented application services/repositories.
- A module must not directly mutate another module's tables.
- Transactions are required for related destructive or multi-record updates.
- Foreign keys and cascade behavior must be explicit and tested.

## 3. Logical data domains

The following domains are conceptual ownership boundaries, not a mandate to create all tables immediately:

| Domain | Example contents |
| --- | --- |
| Provider & Model | Providers, model catalog, capabilities, selections, update history |
| Prompt | Prompt definitions, versions, categories |
| Model Memory | Model-scoped private memory and lifecycle metadata |
| Conversation | Sessions, messages, request/task events, model execution records |
| Project | Project metadata and project-level references |
| Source & File | Original file metadata, source versions, hashes, storage references |
| Librarian | Ingestion jobs, extracted artifacts, analysis, reports, approval states |
| System | Settings metadata, service state, operational records |
| Credentials | Credential references and protected secret metadata |

The initial implementation should create only entities required by the next approved workflow. Extend the schema as each module is implemented.

## 4. File storage

- Original files live in managed file storage, not as the sole copy inside database rows.
- The database stores identifiers, metadata, hashes, storage keys, and relationships.
- Extracted text, chunks, thumbnails, and indexes are derived artifacts.
- A derived artifact must not overwrite the original.
- Storage paths must be generated/validated by the application; do not trust arbitrary browser paths.

## 5. Search

- SQLite FTS5 is the initial lexical/full-text search baseline.
- Search access should be exposed through a replaceable search interface.
- Vector search/embeddings are optional adapters and must not be required for basic document CRUD or lexical retrieval.
- Keep embedding model and vector-store identity/version with derived indexes.
- Rebuilding an index must not require modifying source documents.

## 6. Migration policy

- Use ordered, versioned migrations.
- Migrations must be repeatable in test environments and safe for existing user data.
- Avoid destructive migrations without a backup and explicit compatibility plan.
- Test upgrades from supported prior schema versions.
- Keep SQLite and PostgreSQL behavior aligned where practical; document unavoidable differences.
- Do not assume an ORM alone removes SQL dialect or transaction differences.

## 7. Data integrity and provenance

Use stable IDs, explicit timestamps, ownership/scope fields, and source references. For derived knowledge, preserve source version/hash and locator metadata. Use transactions for approval/publication and multi-record lifecycle transitions.

## 8. Initial design caution

Do not create every possible table in advance. Define conceptual entities and constraints in documentation, then implement the minimum schema needed by the next accepted milestone. This reduces migration burden and prevents unused tables from becoming accidental contracts.

Related: [BACKUP_AND_STORAGE.md](BACKUP_AND_STORAGE.md), [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md), [DOCUMENT_INGESTION.md](DOCUMENT_INGESTION.md).
