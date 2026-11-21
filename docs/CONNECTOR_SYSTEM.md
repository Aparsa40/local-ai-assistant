# Connector System

**Status:** Accepted target design; external connectors remain optional planned integrations.

## 1. Purpose

Connectors integrate external services and data sources through isolated adapters. They must not become hard dependencies of the application or leak service-specific payloads into core domain logic.

A connector is distinct from a model provider:
- Provider: supplies model inference/catalog functionality.
- Connector: exposes an external data source, application, or service.
- Tool: an executable capability invoked through the permissioned Tool Runtime.
A single integration may expose both connector data and tools, but the contracts remain distinct.

## 2. Connector contract

A connector should declare:
- stable connector ID and version;
- supported operations and data types;
- authentication requirements and credential references;
- scopes/permissions requested;
- read/write capabilities;
- synchronization direction and conflict behavior;
- rate limits and operational constraints;
- data provenance and external identifiers.

Connector adapters normalize external data into application-owned representations. They do not bypass repositories or Permission Manager.

## 3. Lifecycle

1. User chooses to configure/connect the service.
2. Application explains the requested scopes.
3. Credentials are stored through the credential boundary.
4. Permission Manager records grants.
5. Connector performs only allowed operations.
6. Imported/derived data retains source identity, timestamps, and provenance.
7. User can pause, disconnect, revoke permissions, or request data handling according to policy.

## 4. Failure isolation

- Connector failure must not prevent local conversations or access to local data.
- External service downtime must not corrupt local records.
- Retry and rate-limit handling must be bounded.
- Synchronization must be idempotent where possible.
- Conflicts must be surfaced, not silently overwritten.

## 5. Data ownership

The external service remains authoritative for its own live records unless the user explicitly imports a copy. The local application owns its local copy and its provenance metadata. A connector must not imply that a cached copy is always current.

## 6. Optional integrations

Potential connectors include Discord, GitHub, local filesystem/project sources, and research/document services. NotebookLM or similar services are optional; they are not the canonical knowledge store.

## 7. Security requirements

- Request least-privilege scopes.
- Keep credentials out of logs and model prompts.
- Validate webhook and imported payloads.
- Treat external content as untrusted input.
- Enforce read/write permissions independently.
- Record audit events for synchronization and writes.

Related: [PERMISSIONS.md](PERMISSIONS.md), [DISCORD_SYNC.md](DISCORD_SYNC.md), [DOCUMENT_INGESTION.md](DOCUMENT_INGESTION.md).
