# Permissions and Tool Safety

**Status:** Phase 5 implementation in progress. Typed authorization contracts, exact-scope grant persistence, and the default-deny PermissionManager are implemented. Tool Runtime, audit-to-runtime wiring, and API/domain integration remain pending. The explicit Tool Registry and bounded schema validation are implemented.  
**Execution plan:** [PHASE_05_EXECUTION_PLAN.md](PHASE_05_EXECUTION_PLAN.md)

## 1. Security model

Authorization is application-owned and default-deny. A model, provider, agent definition, agent run, or tool definition cannot grant permissions. Only trusted application policy code acting on an explicitly authorized owner decision may issue or revoke a grant.

The first implementation is a local single-user application boundary, not hosted multi-user authentication or a security boundary for an exposed server.

## 2. Typed authorization contracts

Implemented in `core/permissions/types.py` and `core/permissions/manager.py`, with persistence in `core/repositories/permission_repository.py`:

- `PermissionSubject`: typed subject category and stable identifier.
- `PermissionResource`: typed resource category and stable identifier.
- `PermissionOperation`: finite operation vocabulary.
- `PermissionScope`: explicit scope type, scope ID, and owner ID.
- `AccessRequest`: subject/resource/operation/scope plus request ID, sensitivity, destination, and timezone-aware request timestamp.
- `PermissionDecision`: allow/deny/approval-required result with stable reason and request reference.
- `PermissionGrant`: exact subject/resource/operation/scope grant with issuer, creation, expiry, and revocation timestamps.

`PermissionManager` returns a structured deny when the policy store is unavailable, fails, or has no exact active match. Grant issuance and revocation are separate privileged operations guarded by `GrantAdministrationPolicy`, whose default implementation denies all changes. Agent-type and agent-run subjects cannot administer grants. The `permission_grants` table is additive and currently created through SQLAlchemy metadata initialization; it is not backed by versioned migrations yet.

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

The current `ToolRegistry` accepts only explicitly registered, versioned definitions. It validates a restricted JSON Schema subset, byte limits, resource type, and operation mapping. It rejects unknown/disabled tools, duplicate registrations, unsupported schema keywords, and unexpected object properties. Destructive and external-side-effect tools must require approval. The registry's public catalog excludes handlers and raw schema internals.

The accepted execution sequence is:

1. Treat model-generated tool calls as untrusted proposals.
2. Resolve a registered tool ID and version.
3. Validate the complete input schema and resource mapping.
4. Ask Permission Manager for an application-side decision.
5. Obtain and consume a one-time approval when required.
6. Execute only through the bounded Tool Runtime.
7. Normalize the result and record a redacted audit event.

A denied action is terminal. It must not be retried through another tool or provider to evade policy. Tool metadata and caller-supplied capability labels are not authorization.

## 5. Context and data boundaries

- Agents receive least-privilege context scoped to the task.
- Model-private memory is not shared with another model/agent by default.
- MemoryService's existing default-deny policy remains authoritative until central integration is complete.
- Knowledge ingestion and publication require explicit grants and approval.
- Local private context must not be sent to cloud providers through implicit fallback.
- Database sessions, engines, ORM entities, repositories, raw SQL, and provider credentials are never agent capabilities.

## 6. Audit and approval

Audit events must capture request, decision, approval transition, execution outcome, and failure with correlation IDs. Persist only redacted metadata: never credentials, raw tokens, private payloads, or unrestricted exception text.

Approval is separate from a persistent grant. The implemented ApprovalService binds a request to the exact action payload SHA-256, subject, target, operation, scope, request ID, and expiry. It requires a separate user approval policy and atomically consumes each approved token at most once. Payload content is not persisted.

AuditService persists append-only events using an explicit metadata allowlist. Unknown metadata fields and private content are dropped; token-like values in allowed fields are redacted. Audit persistence failures are normalized and can be treated as fail-closed by the execution gateway.

## 7. Denials and failures

Return a structured denial reason without leaking secrets. Missing, malformed, expired, revoked, ambiguous, or unsupported authorization means deny. Permission failures are not transient network errors. Tool timeout, schema failure, output-limit failure, and handler exceptions must be normalized without exposing internal details.

## 8. Current integration limits

The current application does not implement user authentication, a credential vault, Knowledge Storage, managed file storage, or a connector framework. Phase 5 must not claim end-to-end protection for those domains until their owning services exist and are integrated. The outstanding Phase 4 WP-4.7 versioned migration framework is also not replaced by SQLAlchemy `create_all()`.

## 9. Acceptance criteria

- Default-deny behavior is tested.
- Grants are exact-scoped, expiring/revocable, and auditable.
- Agents cannot expand their own permissions.
- Approval is action-bound, one-time, and replay-safe.
- Tool execution cannot be invoked outside Tool Runtime.
- Every execution has a prior authorization decision and correlated audit event.
- Destructive and external side effects have approval tests.
- Unsupported resource domains remain explicitly unavailable rather than implicitly allowed.
