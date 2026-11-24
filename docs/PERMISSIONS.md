# Permissions and Tool Safety

**Status:** Phase 5 core foundation merged via PR #15; final operational integration and security acceptance remain in progress. Typed authorization contracts, exact-scope grant persistence, default-deny PermissionManager, action-bound approvals, redacted audit, Tool Registry/Runtime, and local API guards exist. Knowledge Storage was added in Phase 4 PR #16, but its service is not yet wired to the central Permission Manager. Loopback local principal is not authentication.  
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

`PermissionManager` returns a structured deny when the policy store is unavailable, fails, or has no exact active match. Grant issuance and revocation are separate privileged operations guarded by `GrantAdministrationPolicy`, whose default implementation denies all changes. Agent-type and agent-run subjects cannot administer grants. The `permission_grants` table is covered by the Phase 4 versioned SQLite schema migration baseline. The migration runner currently targets SQLite only. The current application composition uses `LocalApplicationPolicy` for the fixed local API principal; a persistent grant repository must be explicitly injected for agent/tool subjects.

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

The current application does not implement user authentication, an encrypted credential vault, or a connector framework. Phase 4 Knowledge Storage and managed file storage now exist, but the KnowledgeService access policy has not yet been adapted to central PermissionManager decisions. No production tool handlers are registered and no model-generated tool-call loop is connected; Phase 6 Agent Runtime must use ToolRuntime rather than bypassing it. Grant and approval services exist, but user-facing administration/review APIs are not yet complete. Direct destructive API actions are not all mediated by action-bound approvals. Keep the server loopback-only and do not treat the local principal as authentication.

## 9. Acceptance criteria

- Default-deny behavior is tested.
- Grants are exact-scoped, expiring/revocable, and auditable.
- Agents cannot expand their own permissions.
- Approval is action-bound, one-time, and replay-safe.
- Tool execution cannot be invoked outside Tool Runtime.
- Every execution has a prior authorization decision and correlated audit event.
- Destructive and external side effects have approval tests.
- Unsupported resource domains remain explicitly unavailable rather than implicitly allowed.
- KnowledgeService reads/writes are mediated by a central PermissionManager adapter.
- Grant issuance/revocation and approval review are exposed only through a local-owner-controlled administration surface.
- Destructive API operations have an explicit approval decision before their side effect, or are clearly classified as local-owner-confirmed actions with tests.
