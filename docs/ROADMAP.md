# Local AI Assistant — 11-Phase Project Roadmap

**Status:** Canonical top-level roadmap  
**Last reviewed:** 2026-11-24  
**Project:** Local AI Assistant

This document is the single source of truth for the project's top-level phase numbering. Technical work packages, implementation increments, and module contracts belong inside these 11 phases; they must not create a competing top-level phase sequence.

## Product direction

Build a local-first, provider-agnostic AI workspace with durable conversations, controlled access to local knowledge, replaceable online/offline model execution, permissioned tools, goal-oriented agents, an auditable AI Librarian workflow, and reliable backup/maintenance.

The local application and its managed data are the system of record. Cloud inference and external integrations are optional. Planned architecture must never be presented as shipped functionality.

## Current implementation baseline

The repository currently contains a FastAPI backend, lightweight Alpine.js browser UI, SQLAlchemy/SQLite persistence, provider adapters, settings/configuration handling, chat streaming, a provider-neutral Interface Manager foundation, and a provider-neutral Local Model Runtime foundation with Ollama as its first adapter.

The current database persists chat sessions/messages, user profile, provider/operator catalogs, live model catalog records, provider/model runtime observations, quota snapshots, catalog sync history, intelligence reports, and local runtime lifecycle state/events.

Phase 4 WP-4.1–WP-4.7 is implemented and merged through PR #16 (`923ad244d91425cca50a64b4c683f62aa53b7fc0`); GitHub Actions passed 228 tests, Python compilation, and frontend syntax validation. SQLite is the only migration backend; PostgreSQL migration support and a separate Windows smoke test remain unverified. Phase 5 PR #15 is merged, but Phase 5 remains in progress: the core Permission Manager, Approval/Audit services, Tool Registry/Runtime, and loopback local API integration exist; operational grant/approval administration, Knowledge authorization integration, direct destructive-action approval coverage, and final security acceptance remain. Authentication and an encrypted credential vault are not implemented. API access is loopback-only with a fixed local principal, not user authentication. Do not expose the current application through a LAN, reverse proxy, or public network.

## Phase 1 — Architecture & Contracts Foundation

**Status:** Completed.

**Goal:** Establish shared product direction, architectural boundaries, data ownership, trust rules, service contracts, and engineering discipline before implementation.

**Execution plan:** [PHASE_01_EXECUTION_PLAN.md](PHASE_01_EXECUTION_PLAN.md)

**Core deliverables:**
- Local-first and provider-agnostic product direction.
- Current implementation versus accepted target design versus planned capability distinction.
- Module responsibilities, dependencies, and non-responsibilities.
- Communication, data ownership, provenance, and security constraints.
- Contribution, testing, documentation, and delivery rules.
- Canonical 11-phase roadmap.

**Exit criteria:** architectural principles and contracts are documented, consistent, and used to scope later phases.

## Phase 2 — Interface Manager

**Status:** Completed and merged through PR #6.

**Goal:** Provide a provider-neutral control plane for provider/model discovery, capability metadata, safe diagnostics, quota visibility, and model invocation.

**Execution plan:** [PHASE_02_EXECUTION_PLAN.md](PHASE_02_EXECUTION_PLAN.md)  
**Module contract:** [INTERFACE_MANAGER.md](INTERFACE_MANAGER.md)

**Core deliverables:**
- Provider adapter contract and registry.
- Interface Manager service boundary.
- Provider/operator catalog and capability access.
- Bounded live model discovery and explicit catalog synchronization.
- Safe connection diagnostics and provider-neutral error categories.
- Evidence-aware quota visibility.
- Chat streaming through the service boundary.
- Persistent operator/live catalog and operational read models.

**Exit criteria:** internal application code uses the provider-neutral service boundary; provider-specific details remain inside adapters; exact model IDs and user selections are preserved; catalog reachability is not confused with inference success.

**Completion evidence:** PR #6 merged with commit `2657b41e3fec1675b29e1612c358e6583ebfb137`.

## Phase 3 — Local Model Runtime

**Status:** Software implementation completed and merged through PR #7. Successful live load/unload on adequately provisioned hardware remains unverified.

**Goal:** Provide a provider-neutral control plane for local inference-engine readiness and model lifecycle.

**Execution plan:** [PHASE_03_EXECUTION_PLAN.md](PHASE_03_EXECUTION_PLAN.md)  
**Module contract:** [LOCAL_MODEL_RUNTIME.md](LOCAL_MODEL_RUNTIME.md)

**Core deliverables:**
- Runtime Manager and Runtime Adapter contracts.
- Ollama Runtime Adapter.
- Runtime readiness, installed inventory, model inspection, and explicit load/unload.
- Bounded operations, normalized errors, and conservative resource admission.
- Application-owned process shutdown only.
- Runtime lifecycle persistence separate from provider catalog and inference status.
- Read-only status/snapshot APIs and explicit POST lifecycle operations.

**Exit criteria:** lifecycle behavior is provider-neutral, bounded, accurately verified, safely persisted, and regression-tested.

**Completion evidence:** PR #7 merged with commit `d30621e85f7f58096f57cf0e40f7dace23a60b21`; PR CI recorded 109 passing tests. Windows smoke checks verified local connectivity, inventory, inspection, and process ownership. The Qwen 0.5B load attempt was hardware-constrained on the observed 4 GB RAM / mechanical-HDD machine; larger models were deliberately not attempted. This is an environment validation gap, not a demonstrated code defect. Do not repeat resource-intensive tests on that machine.

## Phase 4 — Storage & Memory Services

**Status:** Completed and merged through PR #16 (`923ad244d91425cca50a64b4c683f62aa53b7fc0`); CI passed 228 tests.

**Goal:** Consolidate persistence boundaries and introduce domain repositories, conversation storage, durable memory, request context assembly, and knowledge metadata while preserving existing SQLite data.

**Execution plan:** [PHASE_04_EXECUTION_PLAN.md](PHASE_04_EXECUTION_PLAN.md)  
**Completion evidence:** [PR #16](https://github.com/Aparsa40/local-ai-assistant/pull/16), merge commit `923ad244d91425cca50a64b4c683f62aa53b7fc0` (228 CI tests passed).  
**Existing storage reference:** [CATALOG_STORAGE.md](CATALOG_STORAGE.md)

**Work packages:**
1. WP-4.1 — Storage Audit & Contracts.
2. WP-4.2 — Storage Manager.
3. WP-4.3 — Repository Services.
4. WP-4.4 — Conversation Storage.
5. WP-4.5 — Memory Service.
6. WP-4.6 — Context Manager.
7. WP-4.7 — Knowledge Storage & Migration.

**Core deliverables:**
- Centralized Storage Manager with SQLite adapter and future PostgreSQL-compatible boundary.
- Domain-owned Repository Services.
- Conversation and message persistence service.
- Short-term, long-term, episodic, and semantic memory lifecycle.
- Context assembly, relevance ranking, provenance, and token budgets.
- Knowledge source/file metadata and lexical retrieval foundation.
- Versioned migrations tested against an existing database copy.

**Exit criteria:** existing data and Phase 2/3 behavior are preserved; repositories enforce ownership; Memory and Context are independent services; migrations are repeatable; tests and documentation agree with implementation.

## Phase 5 — Tool Runtime & Permission Manager

**Status:** In progress — PR #15 merged; core infrastructure exists, but remaining operational integrations and WP-5.7 acceptance are not complete.

**Goal:** Mediate every protected data access and tool action through application-owned authorization and execution boundaries.

**Execution plan:** [PHASE_05_EXECUTION_PLAN.md](PHASE_05_EXECUTION_PLAN.md)  
**Foundation evidence:** [PR #15](https://github.com/Aparsa40/local-ai-assistant/pull/15), merge commit `342a7fcb0ead3ab9586b671994a5427d812cb175`.  
**Module contracts:** [PERMISSIONS.md](PERMISSIONS.md), [TOOL_RUNTIME.md](TOOL_RUNTIME.md)

**Core deliverables:**
- Permission subjects, resources, operations, scopes, grants, expiry, revocation, and audit events.
- Default-deny policy evaluation.
- Tool registry and normalized tool contracts.
- Isolated/bounded Tool Runtime.
- Approval gates for destructive or externally visible operations.
- Credential access/redaction integration.
- Permission checks for current conversation/profile, memory adapter, provider, runtime, and configuration operations.
- Loopback-only local application policy for the current single-user deployment; hosted authentication is not implemented.
- Knowledge/file/connector protection seams remain unavailable until their owning services exist.

**Exit criteria:** no protected read or tool action occurs without an application-side authorization decision; permissions are scoped, revocable, and tested. The current local policy is not a substitute for authentication. Knowledge/file/connector coverage, credential-vault integration, and hosted multi-user authorization remain outside the implemented scope.

## Phase 6 — Agent Runtime

**Status:** Planned.

**Goal:** Host bounded goal-oriented agents with deterministic lifecycle and state management.

**Core deliverables:**
- Versioned Agent, Task, Run, State, Input, Output, and Completion Criteria contracts.
- Agent Registry and lifecycle manager.
- Task manager, state/checkpoint manager, and bounded execution controller.
- Pause, resume, cancellation, iteration limits, and auditable outcomes.
- Scoped context and permissioned tool access.
- One initial specialized agent with no autonomous external side effects.

**Exit criteria:** one agent completes a bounded task, preserves state, stops safely, and passes deterministic lifecycle and permission tests.

## Phase 7 — Supervisor & Orchestrator

**Status:** Planned.

**Goal:** Coordinate complex work through task decomposition, dependency management, and controlled handoffs.

**Core deliverables:**
- Supervisor as a specialized agent hosted by Agent Runtime.
- Task decomposition and dependency tracking.
- Agent/model capability selection through stable contracts.
- Structured handoff payloads and result aggregation.
- Conflict, incomplete-result, and provenance reporting.
- Bounded orchestration, cancellation, and stop conditions.

**Exit criteria:** the Supervisor coordinates bounded workflows without bypassing Agent Runtime, Permission Manager, Tool Runtime, or validation boundaries.

## Phase 8 — Conversation Agent

**Status:** Planned.

**Goal:** Build the user-facing conversational workflow on top of the completed storage, context, permission, tool, and agent foundations.

**Core deliverables:**
- Conversation Agent contract and lifecycle.
- Request intake, intent classification, and deterministic dispatch.
- Conversation history and authorized context retrieval.
- Online and offline execution strategies through Interface Manager.
- Direct-response versus agent-task handoff.
- Response validation/composition and conversation event recording.
- Explicit fallback behavior that never leaks private local context to cloud providers.

**Exit criteria:** the conversational workflow supports direct answers and bounded agent delegation through one auditable lifecycle, with safe online/offline behavior.

## Phase 9 — Multi-Agent System and Specialized Agents

**Status:** Planned.

**Goal:** Expand from one bounded agent to multiple specialized agents collaborating through explicit contracts.

**Core deliverables:**
- Specialized agent registry and versioned contracts.
- Task assignment, dependencies, structured handoffs, and shared scoped state.
- Sequential collaboration before optional concurrency.
- Supervisor coordination and result evaluation.
- Per-agent model/capability selection.
- Provenance, disagreement, incomplete result, and permission isolation.

**Exit criteria:** multiple agents collaborate on bounded tasks with traceable handoffs, least-privilege context, enforced permissions, and validated output.

## Phase 10 — AI Librarian

**Status:** Planned.

**Goal:** Provide user-controlled source ingestion, analysis, classification, cross-referencing, and knowledge curation.

**Core deliverables:**
- Explicitly authorized source ingestion.
- File/document extraction and incremental change detection.
- Private Librarian Workspace for extracted and derived material.
- Classification, cross-reference, conflict detection, and report generation.
- Source coverage and provenance validation.
- Review and approval workflow before publishing to Approved Knowledge.
- Separation of retrieval knowledge from training-dataset preparation.

**Exit criteria:** no source is ingested without permission; no Librarian report becomes Approved Knowledge without validation and explicit user approval.

## Phase 11 — Backup, Maintenance & Integrations

**Status:** Planned.

**Goal:** Protect persistent user data, support safe maintenance, and add optional external integrations without making them authoritative dependencies.

**Core deliverables:**
- Consistent snapshots of database and managed file storage.
- Backup manifests, integrity verification, and tested restore procedures.
- Encryption and access control for sensitive backup material.
- Retention policies and safe cleanup restricted to designated temporary/cache data.
- Optional connector framework and scoped credentials.
- Discord project-status synchronization and other approved integrations.
- Sync direction, scope, conflict handling, and audit records.
- Optional hosted deployment readiness, including PostgreSQL, authentication, authorization, HTTPS, rate limits, and monitoring.

**Exit criteria:** backup restoration is verified; maintenance cannot delete user records; integrations are optional, scoped, auditable, and disconnectable without losing local data.

## Cross-phase execution rules

- Follow the dedicated execution plan for the active phase.
- Do not skip dependencies or silently change phase numbering.
- Do not mark planned functionality as implemented.
- Do not introduce a module without documenting its boundary and data ownership.
- Do not add speculative database tables before the owning workflow exists.
- Every destructive operation requires explicit scope and safe transaction/rollback strategy.
- Every AI-derived artifact retains provenance and validation state.
- External services remain optional and are never the only copy of project knowledge.
- Every phase requires implementation evidence, tests, documentation, and acceptance review.
- Do not merge pull requests or alter repository protections without explicit authorization.
