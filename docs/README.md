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
| [Provider & Model Intelligence](PROVIDER_MODEL_INTELLIGENCE.md) | Model evidence analysis, runtime/offline reports, and provider intelligence |
| [Local Model Runtime](LOCAL_MODEL_RUNTIME.md) | Provider-neutral local runtime lifecycle, Ollama adapter, persistence, API, and acceptance criteria |
| [Operator Catalogs](OPERATOR_CATALOGS.md) | Operator-level discovery, free-tier caveats, quota visibility, and evidence policy |
| [Catalog Storage Schema](CATALOG_STORAGE.md) | Persistent operator/live catalog tables, sync lifecycle, and evidence rules |
| [Provider System](PROVIDER_SYSTEM.md) | Provider adapters, discovery, errors, credentials, and quotas |
| [Model Manager](MODEL_MANAGER.md) | Model catalog records, capability evidence, lifecycle, and safe updates |
| [Agent Runtime](AGENT_RUNTIME.md) | Agent contracts, lifecycle, execution loop, online/offline operation, and multi-agent boundary |
| [AI Orchestration](AI_ORCHESTRATION.md) | Conversation Processing, online/offline engines, and Supervisor |
| [Permissions](PERMISSIONS.md) | Default-deny access control, tool mediation, and approval gates |

## Supporting references

- [Provider Capabilities](PROVIDER_CAPABILITIES.md) — provider capability notes and operational references.
- [Versioning](VERSIONING.md) — semantic versioning policy.

## Planned module contracts

The following contracts are planned for their owning roadmap phases and are not yet documented as complete specifications: Connector System, Memory Architecture, Discord Sync, Document Ingestion / AI Librarian, Database Schema / migrations, and Backup & Storage.

## Status vocabulary

- **Implemented:** present in the current codebase and verified to the extent stated.
- **Accepted:** an agreed architectural decision or module contract, not necessarily implemented.
- **Planned:** intended future work that has not yet been completed.
- **Experimental:** exists but is not yet a stable contract.

If a document and the current code differ, do not silently assume either is correct. Determine whether the document is describing target architecture or current behavior, then update the appropriate status and raise unresolved conflicts.
