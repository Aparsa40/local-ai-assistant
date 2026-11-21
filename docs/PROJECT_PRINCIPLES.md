# Project Principles and Non-Negotiable Constraints

**Status:** Accepted architectural principles  
**Scope:** Entire Local AI Assistant project  
**Audience:** Human contributors, AI coding agents, reviewers, and future maintainers

This document defines the constraints that every implementation, refactor, integration, and delegated AI task must respect. Detailed designs may evolve, but a change that weakens one of these principles is an architectural change and must be explicitly reviewed and approved. A model or contributor must never silently reinterpret or override these principles.

## 1. Product identity

The project is a privacy-conscious, local-first, provider-agnostic AI workspace. It is not merely a chat UI and must not become dependent on one cloud vendor, one model family, or one external knowledge service.

## 2. Core principles

### 2.1 Local First

- The application must remain useful without an internet connection for capabilities that can be fulfilled locally.
- Local inference and local data access must not require a cloud provider.
- Internet connectivity alone does not imply that a usable online model is available.
- When online providers are unavailable, the system must evaluate the local execution path.
- The application must be honest about capabilities that require an LLM; deterministic search, retrieval, extraction, and fixed workflows must not be presented as general-purpose reasoning.

### 2.2 Provider Agnostic

- No core module may depend directly on a specific provider SDK, provider-specific model ID, or vendor response format.
- Provider-specific behavior belongs behind provider adapters and normalized contracts.
- Providers and models must be independently replaceable.
- Provider failure, quota exhaustion, account restrictions, or retirement must not corrupt conversations or make local data inaccessible.

### 2.3 Connector Agnostic

- External services and tools must be integrated through isolated connectors/adapters.
- A connector is optional unless a separately approved product requirement states otherwise.
- Core application workflows must not depend on Discord, NotebookLM, GitHub, or another external service being available.
- Connector-specific identifiers and payloads must not leak into domain logic.

### 2.4 Shared Knowledge, Isolated Model Memory

- The application may expose one shared, permission-controlled knowledge layer to authorized modules and models.
- Shared knowledge consists of approved sources and derived knowledge with provenance and access policy.
- Each model's private memory remains logically isolated by owner/model scope.
- One model must not read, export, or inherit another model's private memory without explicit authorization.
- Shared knowledge does not mean unrestricted access to all conversations, files, or model memories.

### 2.5 Permission First

- Access to files, conversations, model memories, connectors, tools, and write operations is denied unless an applicable permission has been granted.
- A model may propose a tool call; it does not authorize or execute that call.
- Permission checks must be enforced by application-controlled services, not by prompt instructions alone.
- Permissions must be scoped, auditable, and revocable.
- Source ingestion permission and final knowledge publication approval are separate decisions.

### 2.6 Replaceable Components

- Database engines, repositories, file storage backends, vector stores, embedding models, providers, connectors, and execution engines must be replaceable behind stable interfaces where practical.
- SQLite is the local database target; PostgreSQL is the online/hosted database target.
- SQLite FTS5 is the initial lexical-search baseline. Vector search is an optional adapter, not a mandatory foundation.
- Original files must remain independent of database records and derived indexes.

### 2.7 Persistent Context and Provenance

- Important project decisions, conversation records, source references, and approved knowledge must persist according to user-controlled retention and permission policies.
- Derived knowledge must retain links to the source material and the processing history that produced it.
- A model-generated summary is not an authoritative source merely because it was saved.
- The system must distinguish source facts, model inferences, and user-approved decisions.

### 2.8 Incremental and Verifiable Development

- Each implementation phase must have a defined scope, tests, documentation updates, and acceptance criteria.
- Do not implement future roadmap functionality as if it were already available.
- Prefer small, reviewable changes over broad rewrites.
- Database changes must be migration-based and backward-conscious.
- Existing behavior must not be removed without an explicit requirement and regression coverage.

## 3. Data ownership rules

- Every persistent data category has a clearly defined owning module or repository boundary.
- A module may access another domain only through its documented API/repository contract and applicable permissions.
- The AI Librarian does not own or modify original source files.
- Backup services may read consistent snapshots of persistent data but do not become owners of those records.
- Maintenance services may clean designated temporary/cache data only; they must not delete primary user data as a side effect.

## 4. AI Librarian publication gate

The Librarian has two independent gates:

1. **Source Ingestion Permission:** the user authorizes a specific source/scope and permitted operations, including reading, extraction, analysis, and storing extracted working material in the Librarian workspace.
2. **Report Approval:** after analysis and validation, the user reviews the resulting report. Only explicit approval may publish it into Approved Knowledge.

Without the first permission, no ingestion occurs. Without the second approval, the report remains non-authoritative and unavailable as generally approved knowledge.

## 5. Architectural change control

A change to these principles requires all of the following:

1. Explain the problem the existing principle cannot solve.
2. Identify affected modules, data domains, permissions, and migration implications.
3. Describe alternatives and failure modes.
4. Update this document and all affected contracts in the same change.
5. Add or update tests and acceptance criteria.
6. Obtain explicit project-owner approval before implementation.

AI coding agents must stop and ask for clarification when a task appears to conflict with this document. They must not resolve such a conflict by silently changing the principle.

## 6. Document precedence

When project documents disagree, use this order:

1. Explicit, latest project-owner decisions recorded in an accepted architecture decision record or this principles document.
2. This document for non-negotiable constraints.
3. The accepted target architecture and module contracts.
4. The current roadmap for sequencing and status.
5. Existing code and implementation notes for what is actually shipped.
6. Suggestions, examples, generated plans, and external model output.

A lower-precedence source cannot silently override a higher-precedence decision. If a conflict is discovered, record it and request a decision.
