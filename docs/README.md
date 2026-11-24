# Documentation Index

This directory is the architectural, execution, and engineering reference for Local AI Assistant.

## Start here

1. [Project Principles](PROJECT_PRINCIPLES.md) — non-negotiable constraints and change control.
2. [Architecture](ARCHITECTURE.md) — current implementation snapshot and accepted target architecture.
3. [Canonical 11-Phase Roadmap](ROADMAP.md) — top-level phase sequence, status, dependencies, and exit criteria.
4. [AI Contribution Guide](AI_CONTRIBUTION_GUIDE.md) — required reading and execution rules for delegated coding agents.

## Phase execution plans

These are the authoritative step-by-step plans. Follow the active phase document in order; module specifications supplement, but do not replace, the execution plan.

| Phase | Execution plan | Status |
|---|---|---|
| 1 — Architecture & Contracts Foundation | [PHASE_01_EXECUTION_PLAN.md](PHASE_01_EXECUTION_PLAN.md) | Completed |
| 2 — Interface Manager | [PHASE_02_EXECUTION_PLAN.md](PHASE_02_EXECUTION_PLAN.md) | Completed — PR #6 merged |
| 3 — Local Model Runtime | [PHASE_03_EXECUTION_PLAN.md](PHASE_03_EXECUTION_PLAN.md) | Software complete — hardware load validation deferred |
| 4 — Storage & Memory Services | [PHASE_04_EXECUTION_PLAN.md](PHASE_04_EXECUTION_PLAN.md) | WP-4.1–WP-4.6 implemented and validated; WP-4.7 Knowledge Storage & Migration remains pending |
| 5 — Tool Runtime & Permission Manager | [PHASE_05_EXECUTION_PLAN.md](PHASE_05_EXECUTION_PLAN.md) | In progress — PR #15; WP-5.1 through WP-5.4 implemented and CI-validated |
| 6 — Agent Runtime | Defined in [ROADMAP.md](ROADMAP.md) | Planned |
| 7 — Supervisor & Orchestrator | Defined in [ROADMAP.md](ROADMAP.md) | Planned |
| 8 — Conversation Agent | Defined in [ROADMAP.md](ROADMAP.md) | Planned |
| 9 — Multi-Agent System and Specialized Agents | Defined in [ROADMAP.md](ROADMAP.md) | Planned |
| 10 — AI Librarian | Defined in [ROADMAP.md](ROADMAP.md) | Planned |
| 11 — Backup, Maintenance & Integrations | Defined in [ROADMAP.md](ROADMAP.md) | Planned |

A dedicated execution plan should be added for each later phase before implementation of that phase begins.

## Module specifications

| Document | Scope |
|---|---|
| [Interface Manager](INTERFACE_MANAGER.md) | Provider/model control plane and internal service contract |
| [Provider & Model Intelligence](PROVIDER_MODEL_INTELLIGENCE.md) | Model evidence analysis, runtime/offline reports, and provider intelligence |
| [Local Model Runtime](LOCAL_MODEL_RUNTIME.md) | Provider-neutral local runtime lifecycle, Ollama adapter, persistence, API, and acceptance criteria |
| [Operator Catalogs](OPERATOR_CATALOGS.md) | Operator-level discovery, free-tier caveats, quota visibility, and evidence policy |
| [Catalog Storage Schema](CATALOG_STORAGE.md) | Persistent operator/live catalog tables, sync lifecycle, and evidence rules |
| [Conversation & Profile Services](CONVERSATION_PROFILE_SERVICES.md) | Conversation persistence, chat-turn durability, profile validation, and avatar lifecycle |
| [Memory Service](MEMORY_SERVICE.md) | Scoped memory lifecycle, provenance, deduplication, retention, and deterministic retrieval |
| [Context Manager](CONTEXT_MANAGER.md) | Request-scoped context assembly, explicit memory scopes, provenance, ranking, and token budgeting |
| [Permissions](PERMISSIONS.md) | Implemented authorization contracts, exact-scope grants, approvals, and audit service |
| [Tool Runtime](TOOL_RUNTIME.md) | Tool Registry contracts, schema validation, risk classes, and bounded execution target |
| [Provider System](PROVIDER_SYSTEM.md) | Provider adapters, discovery, errors, credentials, and quotas |
| [Model Manager](MODEL_MANAGER.md) | Model catalog records, capability evidence, lifecycle, and safe updates |
| [Agent Runtime](AGENT_RUNTIME.md) | Agent contracts, lifecycle, execution loop, online/offline operation, and multi-agent boundary |
| [AI Orchestration](AI_ORCHESTRATION.md) | Conversation Processing, online/offline engines, and Supervisor |

## Supporting references

- [Provider Capabilities](PROVIDER_CAPABILITIES.md) — provider capability notes and operational references.
- [Versioning](VERSIONING.md) — semantic versioning policy.

## Status vocabulary

- **Implemented:** present in the current codebase and verified to the extent stated.
- **Completed:** the phase's defined deliverables and acceptance criteria have been met; any explicit validation gap remains documented.
- **Accepted:** an agreed architectural decision or module contract, not necessarily implemented.
- **Planned:** intended future work that has not yet been completed.
- **Experimental:** exists but is not yet a stable contract.

If a document and current code differ, do not silently assume either is correct. Determine whether the document describes target architecture or current behavior, then update the appropriate status and record unresolved conflicts.
