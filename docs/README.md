# Documentation Index

This directory is the architectural and engineering reference for Local AI Assistant.

## Start here

1. [Project Principles](PROJECT_PRINCIPLES.md) — non-negotiable constraints and change control.
2. [Architecture](ARCHITECTURE.md) — current implementation snapshot and accepted target architecture.
3. [Roadmap](ROADMAP.md) — milestones, dependencies, and acceptance criteria.
4. [AI Contribution Guide](AI_CONTRIBUTION_GUIDE.md) — required reading and execution rules for delegated coding agents.

## Module specifications

| Document | Scope |
| --- | --- |
| [Interface Manager](INTERFACE_MANAGER.md) | Provider/model control plane and internal service contract |
| [Provider System](PROVIDER_SYSTEM.md) | Provider adapters, discovery, errors, credentials, and quotas |
| [Model Manager](MODEL_MANAGER.md) | Model catalog, capability metadata, labels, and safe updates |
| [Connector System](CONNECTOR_SYSTEM.md) | Optional external service integrations |
| [Permissions](PERMISSIONS.md) | Default-deny access control, tool mediation, and approval gates |
| [Memory Architecture](MEMORY_ARCHITECTURE.md) | Conversation history, model-private memory, and shared knowledge |
| [Discord Sync](DISCORD_SYNC.md) | Optional Discord status/context synchronization |
| [Document Ingestion](DOCUMENT_INGESTION.md) | Source ingestion and AI Librarian workflow |
| [AI Orchestration](AI_ORCHESTRATION.md) | Conversation Processing, online/offline engines, and Supervisor |
| [Database Schema](DATABASE_SCHEMA.md) | SQLite/PostgreSQL direction, repositories, migrations, and search |
| [Backup and Storage](BACKUP_AND_STORAGE.md) | Durable storage, snapshots, restore, and maintenance |

## Supporting references

- [Provider Capabilities](PROVIDER_CAPABILITIES.md) — provider capability notes and operational references.
- [Versioning](VERSIONING.md) — semantic versioning policy.

## Status vocabulary

- **Implemented:** present in the current codebase and verified to the extent stated.
- **Accepted:** an agreed architectural decision or module contract, not necessarily implemented.
- **Planned:** intended future work that has not yet been completed.
- **Experimental:** exists but is not yet a stable contract.

If a document and the current code differ, do not silently assume either is correct. Determine whether the document is describing target architecture or current behavior, then update the appropriate status and raise unresolved conflicts.
