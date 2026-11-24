# Permissions and Tool Safety

**Status:** Phase 5 implementation complete on `feat/phase-5-operational-authorization`; PR/merge pending. Core authorization, local-owner grant administration, approval review, destructive API approval, Knowledge adapter integration, and audit APIs are implemented. Latest CI passed 235 tests plus compile and frontend syntax checks.  
**Execution plan:** [PHASE_05_EXECUTION_PLAN.md](PHASE_05_EXECUTION_PLAN.md)

## 1. Security model

Authorization is application-owned and default-deny. A model, provider, agent definition, agent run, or tool definition cannot grant permissions. Only trusted application policy code acting on an explicitly authorized owner decision may issue or revoke a grant.

The first implementation is a local single-user application boundary, not hosted multi-user authentication or a security boundary for an exposed server. API dependencies reject non-loopback client addresses and issue only the fixed `local-api` principal; this is not proof of an individual user's identity. Do not expose the application through a LAN, reverse proxy, or public network without adding real authentication and a new threat review.

## 2. Typed authorization contracts

Implemented in `core/permissions/types.py` and `core/permissions/manager.py`, with persistence in `core/repositories/permission_repository.py`:

- `PermissionSubject`: typed subject category and stable identifier.
- `PermissionResource`: typed resource category and stable identifier.
- `PermissionOperation`: finite operation vocabulary.
- `PermissionScope`: explicit scope type, scope ID, and owner ID.
- `AccessRequest`: subject/resource/operation/scope plus request ID, sensitivity, destination, and timezone-aware request timestamp.
- `PermissionDecision`: allow/deny/approval-required result with stable reason and request reference.
- `PermissionGrant`: exact subject/resource/operation/scope grant with issuer, creation, expiry, revocation, and optional approval-required state.

`PermissionManager` returns a structured deny when the policy store is unavailable, fails, or has no exact active match. Grant issuance and revocation are separate privileged operations guarded by `GrantAdministrationPolicy`, whose default implementation denies all changes. Agent-type and agent-run subjects cannot administer grants. The permission grant, approval, and audit records are ORM metadata-owned. The Phase 4 migration runner provides ordered SQLite revisions for the Knowledge schema and legacy additive columns; it does not currently provide PostgreSQL migrations or dedicated permission-table revisions.

Identifiers reject empty values, wildcard-like values, control characters, and excessive length. These contracts are descriptive data only; constructing a request, decision, or grant does not itself authorize an operation.

## 3. Permission decision dimensions

Every protected operation must be evaluated against:

- **Subject:** user, trusted application service, agent type, or specific agent run.
- **Resource:** conversation, memory scope, profile, tool, file, knowledge source, connector, provider credential, or a future explicitly registered resource.
- **Operation:** read, create, update, delete, execute, publish, transmit, approve, or administer.
- **Scope:** exact local/user/conversation/task/project/folder/provider scope and owner.
- **Conditions:** expiry, revocation, approval requirement, sensitivity, and allowed destination.

No wildcard, inferred owner, or implicit cross-scope grant is valid.

## 4. Tool execution boundary

The current `ToolRegistry` accepts only explicitly registered, versioned definitions. It validates a restricted JSON Schema subset, byte limits, resource type, and operation mapping. It rejects unknown/disabled tools, duplicate registrations, unsupported schema keywords, and unexpected object properties. Destructive and external-side-effect tools must require approval. The registry's public catalog exposes the validated input schema needed to form a proposal, but never exposes the registered handler.

The implemented ToolRuntime execution sequence is:

1. Treat model-generated tool calls as untrusted proposals.
2. Resolve a registered tool ID and version.
3. Validate the complete input schema and resource mapping.
4. Ask Permission Manager for an application-side decision and persist the decision event.
5. Obtain and consume a one-time approval when required.
6. Recheck permission immediately before executing through Tool Runtime.
7. Normalize the result and persist a redacted audit event.

A denied action is terminal. It must not be retried through another tool or provider to evade policy. Tool metadata and caller-supplied capability labels are not authorization.

## 5. Context and data boundaries

- Agents receive least-privilege context scoped to the task.
- Model-private memory is not shared with another model/agent by default.
- MemoryService remains default-deny unless an explicit policy is injected; the tested `PermissionManagerMemoryAccessPolicy` adapter routes exact memory scopes through central authorization. The current chat route does not attach memory scopes implicitly.
- Knowledge ingestion and publication require explicit grants and approval.
- Local private context must not be sent to cloud providers through implicit fallback.
- Database sessions, engines, ORM entities, repositories, raw SQL, and provider credentials are never agent capabilities.

## 6. Audit and approval

Audit events must capture request, decision, approval transition, execution outcome, and failure with correlation IDs. Persist only redacted metadata: never credentials, raw tokens, private payloads, or unrestricted exception text.

Approval is separate from a persistent grant. The implemented ApprovalService binds a request to the exact action payload SHA-256, subject, target, operation, scope, request ID, and expiry. It requires a separate user approval policy and atomically consumes each approved token at most once. Request, decision, expiry, and consumption transitions are audited. If the required audit write for a request/approval decision fails, the approval is invalidated; a consumed token is never replayed. Payload content is not persisted.

AuditService persists append-only events using an explicit metadata allowlist. Unknown metadata fields and private content are dropped; token-like values in allowed fields are redacted. Audit persistence failures are normalized and can be treated as fail-closed by the execution gateway.

## 7. Denials and failures

Return a structured denial reason without leaking secrets. Missing, malformed, expired, revoked, ambiguous, or unsupported authorization means deny. Permission failures are not transient network errors. Tool timeout, schema failure, output-limit failure, and handler exceptions must be normalized without exposing internal details.

## 8. Current integration limits

The local API uses a fixed `local-api` service principal and fixed `local-user` owner identity behind loopback and same-origin checks. This is not user authentication and is not safe for hosted/multi-user exposure. There is no encrypted credential vault or connector framework. KnowledgeService is integrated through exact persisted grants, but generic managed-file upload APIs are not exposed. No production tool handlers or model-generated tool-call loop are registered; Phase 6 Agent Runtime owns that integration and must call ToolRuntime. Permission/approval/audit records are currently created through ORM metadata; SQLite migrations are implemented for Phase 4 Knowledge but PostgreSQL is not supported.

## 9. Acceptance criteria

- Default-deny behavior is tested.
- Grants are exact-scoped, expiring/revocable, and auditable.
- Agents cannot expand their own permissions.
- Approval is action-bound, one-time, and replay-safe.
- Tool execution cannot be invoked outside Tool Runtime.
- Every execution has a prior authorization decision and correlated audit event.
- Destructive and external side effects have approval tests.
- Unsupported resource domains remain explicitly unavailable rather than implicitly allowed.
- KnowledgeService creation, updates, and reads are authorized by separate exact-scope grants.
- Grant administration and approval decisions are restricted to the fixed local owner behind loopback/same-origin checks.
- Session deletion, avatar deletion, and runtime shutdown require action-bound, expiring, one-time approvals.
- The local owner identity is a single-user convenience boundary, not authentication.
