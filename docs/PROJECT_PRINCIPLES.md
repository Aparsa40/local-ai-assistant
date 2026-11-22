# Project Principles

**Status:** Accepted architecture constraints.

## 1. Product and data direction
- Local-first by default: local data remains the system of record; cloud services are optional execution providers.
- Provider-agnostic: application workflows depend on stable contracts, not vendor SDKs or payloads.
- User control: provider/model changes, data ingestion, publication, destructive operations, and external side effects follow explicit user policy.
- Offline-capable: deterministic local workflows must remain useful without cloud inference.

## 2. Architecture boundaries
- Modules own their data and expose documented APIs/repositories.
- A module must not mutate another module's tables or internal state directly.
- Agents own goal-oriented workflows; ordinary deterministic components remain services.
- Agent Runtime enforces lifecycle, budgets, permissions, and stop conditions. Model output never grants itself authority.
- Interface Manager provides provider/model facts and execution; it does not plan tasks or certify factual correctness.
- Response Validator & Composer is independent of provider adapters and is shared by online/offline paths.

## 3. Trust and security
- Default deny for tools, files, memories, connectors, and cross-domain reads.
- Treat model output, imported files, and external API responses as untrusted input.
- Keep credentials out of browser payloads, prompts, logs, and ordinary audit events.
- Never send private local context to a cloud provider as an implicit fallback.
- Require approval for destructive or externally visible actions.
- Unknown capability, quota, availability, and provenance values remain unknown.

## 4. Data lifecycle
- Preserve original source files separately from extracted text and derived artifacts.
- Every AI-derived artifact retains source/model provenance and validation state.
- Librarian drafts are not approved knowledge. Publication requires validation and user approval.
- Backups must include consistent persistent data snapshots; cache cleanup must never delete user records.

## 5. Engineering discipline
- Label every capability Implemented, Accepted, Planned, or Experimental.
- Add tests for behavior and security boundaries; do not remove/skip tests to obtain a green build.
- Preserve stable IDs and existing user selections during catalog refresh.
- Prefer small, reversible increments with migration and rollback plans.
- A feature is not complete until code, tests, docs, and acceptance criteria agree.
