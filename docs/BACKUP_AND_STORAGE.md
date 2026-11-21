# Backup, File Storage, and Maintenance

**Status:** Accepted direction; implementation is planned incrementally.

## 1. Purpose

This document separates durable user data, original files, derived artifacts, and regenerable temporary data. Backup and Maintenance have different responsibilities and must not be treated as one unrestricted cleanup service.

## 2. Storage categories

| Category | Examples | Policy |
| --- | --- | --- |
| Persistent database data | Conversations, settings metadata, projects, approved knowledge | Back up through consistent snapshots |
| Original files | User documents and project files | Preserve independently and include in backup manifests |
| Derived data | Extracted text, chunks, thumbnails, indexes, Librarian reports | Track provenance; retention depends on state and policy |
| Temporary/cache data | Temporary uploads, transient responses, rebuildable cache | Explicitly scoped cleanup |
| Credentials/secrets | API keys, tokens, encryption material | Protected storage; never ordinary plaintext backup |

## 3. Backup Manager

Backup Manager protects all persistent application data, not only Librarian records. It is a reader/snapshot coordinator, not the owner of other modules' data.

- Request consistent snapshots through owner-controlled APIs or repository snapshot services.
- Include database state and referenced original files.
- Generate a manifest with backup ID, creation time, schema version, file hashes, included domains, and completion status.
- Verify snapshot integrity.
- Support restore testing and clear recovery instructions.
- Encrypt sensitive backup content and protect encryption keys separately.
- Never expose credentials in logs or backup manifests.

A backup must be internally consistent: database references must not point to files omitted from the snapshot.

## 4. Restore

- Restore into a controlled target location.
- Validate manifest, hashes, and schema compatibility before replacing active data.
- Preserve the current state or create a recovery point before destructive restore.
- Report partial failures explicitly.
- Test restore procedures regularly; a backup that has never been restored is not proven recoverable.

## 5. Maintenance Manager

Maintenance is restricted to designated temporary/cache locations and approved retention rules.

- Preview affected items before cleanup where user data could be ambiguous.
- Use allowlisted roots and path validation.
- Never accept arbitrary deletion paths from the UI.
- Do not delete conversations, messages, original documents, approved knowledge, credentials, or project data as part of cache cleanup.
- Do not delete derived knowledge unless its owner and retention policy authorize it.
- Record cleanup results and failures.

## 6. Ownership and access

- Backup reads via snapshot interfaces; domain owners retain write authority.
- Maintenance operates only on data explicitly designated as temporary/cache or expired under an approved policy.
- File Management owns original-file lifecycle.
- Librarian owns its working artifacts and report workflow, not source files.
- Database repositories own their domain records.

## 7. Credentials and encryption

- API keys and tokens must not be copied into plaintext backups.
- If credential backup is supported, it must be encrypted using a key-management approach separate from the backup archive.
- Do not claim encryption until implemented and tested.
- Logs, manifests, and diagnostics must redact secret values.

Related: [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md), [PERMISSIONS.md](PERMISSIONS.md), [PROJECT_PRINCIPLES.md](PROJECT_PRINCIPLES.md).
