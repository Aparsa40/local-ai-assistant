# Permission and Authorization Architecture

**Status:** Accepted security boundary.

## 1. Purpose

Permission Manager is the application-controlled authority for access to user data, tools, connectors, and sensitive operations. A model's request or prompt instruction is never itself a permission grant.

## 2. Default-deny model

Access is denied unless an applicable grant exists. Grants should be scoped by:
- actor/subject (user, module, model, connector, tool);
- resource/source and optional dataset/project;
- permitted operations;
- scope/constraints;
- grant time and grantor;
- expiry where applicable;
- status and revocation state;
- provenance/audit reference.

Possible operations include read, list, extract, analyze, search, export, write, delete, sync, and store-derived-data. The exact operation set should be normalized before implementation.

## 3. Model and tool execution

1. A model proposes a tool call or requests data.
2. Conversation Processing identifies the requesting actor and intended resource.
3. Permission Manager evaluates the request against explicit grants and policy.
4. If allowed, Tool Runtime executes the operation with least privilege.
5. Inputs, outputs, decision, and failures are audited with secrets redacted.
6. Sensitive or destructive actions may require a fresh user confirmation even when a standing grant exists.

Models cannot grant themselves permissions, change permission records, or bypass Tool Runtime.

## 4. Source ingestion permission

AI Librarian requires a distinct Source Ingestion Permission before it can read or extract a source. The grant must identify the source or dataset and permitted operations, including whether extracted working material may be stored in the Librarian Workspace.

No grant means no reading, extraction, or analysis. A general permission to use the application does not imply permission to ingest all conversations, files, projects, or model memories.

## 5. Report approval

Source permission and report approval are separate gates.

- Source permission allows processing of a defined source/scope.
- Report approval allows a specific validated report/version to be published into Approved Knowledge.

A report awaiting approval is not generally available as approved knowledge. Approval must identify the report version reviewed by the user.

## 6. Revocation and derived data

Permissions must be revocable. After revocation:
- new access and future processing using that grant are blocked;
- cached access paths must be re-evaluated;
- existing derived data must follow an explicit retention/deletion policy.

Revocation must not silently imply that all derived data is deleted. The system must preserve enough provenance to identify affected artifacts and offer the applicable user-controlled handling.

## 7. Shared knowledge and private memory

Shared Approved Knowledge is accessible only to modules/models authorized by policy. Model-private memory remains isolated by model/owner scope. A shared knowledge grant does not authorize access to another model's private memory.

## 8. Audit and tests

Record permission grants, changes, revocations, decisions, and sensitive operations. Tests must cover:
- default denial;
- scope mismatch;
- expired/revoked grants;
- cross-model memory isolation;
- connector read/write boundaries;
- Librarian ingestion gate;
- report publication gate;
- sensitive operation confirmation.

Related: [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md), [DOCUMENT_INGESTION.md](DOCUMENT_INGESTION.md), [CONNECTOR_SYSTEM.md](CONNECTOR_SYSTEM.md).
