# Phase 5 — Tool Runtime & Permission Manager

**Project:** Local AI Assistant  
**Phase:** 5 of 11  
**Document type:** Authoritative execution plan  
**Status:** In progress — WP-5.1 and WP-5.2 implemented and CI-validated; WP-5.3–WP-5.7 pending  
**Execution branch:** `feat/phase-5-permission-manager-tool-runtime` (created directly from `main`)  
**Delivery:** One branch and one pull request for the entire phase unless a documented size or CI constraint requires a merge boundary.  
**Last reviewed:** 2026-11-24

## 1. Purpose

Implement one application-owned authorization and tool-execution boundary. Every protected data read, protected write, and tool invocation must be evaluated by deterministic policy code; model output, agent declarations, tool metadata, and caller-supplied capability labels are never authorization.

The phase builds on Phase 4's Storage Manager, repositories, Conversation/Profile Services, Memory Service, and Context Manager. It must not expose database sessions, engines, ORM entities, repositories, raw SQL, provider credentials, or arbitrary filesystem/process access to agents or model-generated tool calls.

## 2. Dependency and baseline audit

The repository contains:
- StorageManager and explicit session/transaction boundaries.
- Domain repositories for catalog, runtime, profile, sessions, messages, and memories.
- ConversationService, ProfileService, MemoryService, and ContextManager.
- A default-deny MemoryAccessPolicy seam.
- Accepted target contracts in `PERMISSIONS.md`, `AGENT_RUNTIME.md`, and `AI_ORCHESTRATION.md`.

Important dependency limitation: the Phase 4 execution plan also defines WP-4.7 (Knowledge Storage & Migration), but the current main-branch documentation and implementation evidence do not establish that work package as complete. Phase 5 therefore integrates only existing domains and provides explicit adapter contracts for future Knowledge, managed-file, and connector services. It must not claim those unavailable domains are already protected end-to-end. New Phase 5 persistence must use the existing SQLAlchemy metadata/Storage Manager conventions and must clearly document that this does not replace the outstanding versioned migration framework.

Before implementation, verify the current `main` head, open-PR state, test baseline, database model conventions, and application composition points. Do not reset or mutate the user's local database.

## 3. WP-5.1 audit findings (2026-11-24)

The initial code and API audit found the following facts:

- `main.py` creates the FastAPI application without an authentication dependency or request-principal resolver. Profile, settings, provider, runtime, session, and chat routes are currently reachable without an application-level authenticated subject.
- ConversationService and ProfileService are application services that receive a database session from API composition. They do not implement authorization themselves.
- MemoryService already uses an injected MemoryAccessPolicy and defaults to DenyAllMemoryAccessPolicy. ContextManager delegates memory retrieval to MemoryService and does not yet call a central PermissionManager.
- Provider credentials are loaded through ConfigManager. The repository documentation explicitly says current local credential storage is not an encrypted vault.
- Local Model Runtime exposes explicit model load/unload and runtime shutdown operations. Shutdown is limited to processes owned by the application, but API-level authorization is not yet present.
- No Tool Registry or Tool Runtime execution gateway exists in the current baseline.
- StorageManager is the centralized persistence lifecycle. Repositories own ORM queries; application services and API composition are the only appropriate integration points. No session/repository object may cross into a future tool handler or model context.

**Threat implications and implementation constraints:**

1. Until authentication is introduced, a local subject can only represent the trusted local application boundary; it must not be presented as user authentication or safe hosted multi-user authorization.
2. Deployment must remain loopback/local-only while API authentication is absent. Phase 5 will not silently add a permissive network principal.
3. Existing routes cannot all be switched to default-deny without first introducing an explicit trusted local application policy and clear composition boundary. Any such policy must be narrow, testable, and documented as local single-user behavior.
4. Destructive runtime and conversation actions need an approval/risk policy; read-only status/catalog endpoints must not be confused with execution operations.
5. Provider credential access remains unavailable to tools by default. No credential value may be passed to tool handlers or audit metadata.

The audit did not inspect or mutate the user's local SQLite database and did not run hardware-intensive model operations.

## 4. Security invariants

1. **Default deny:** missing, malformed, expired, revoked, ambiguous, or unsupported authorization means deny.
2. **No self-grant:** a model, tool, agent definition, agent run, provider, or untrusted input cannot create or widen grants.
3. **Explicit scope:** every decision binds subject, resource, operation, and scope; no wildcard or inferred owner/scope expansion.
4. **Least privilege:** grants are narrow, time-bounded where appropriate, and revocable.
5. **Approval is separate:** approval is a one-time, bound authorization for a specific pending action, not a persistent grant.
6. **Policy before side effect:** validate tool identity and input schema, authorize, resolve any required approval, then execute.
7. **No bypass/retry:** denial is terminal for that action; fallback to another tool/provider cannot evade it.
8. **Auditable:** record request, decision, approval, execution outcome, and failure using redacted structured metadata.
9. **Secret-safe:** never put credentials, raw secret values, full private payloads, or unrestricted exception text in audit records or user-facing denial messages.
10. **Bounded execution:** each tool has explicit timeout, input/output limits, and a declared side-effect class.
11. **No implicit cloud egress:** private local context is never transmitted to a provider/tool as an unannounced fallback.
12. **No direct infrastructure access:** callers receive typed contracts and explicit capabilities only; no DB/session/repository/engine or arbitrary code execution.

## 5. Domain contracts

The public contracts should be immutable typed values where practical:

- `PermissionSubject`: subject type and stable subject ID (user, application service, agent type, or run).
- `PermissionResource`: resource type and stable resource ID (conversation, memory scope, file, tool, connector, provider credential, or future domain resource).
- `PermissionOperation`: a finite operation vocabulary (read, create, update, delete, execute, publish, transmit, approve, administer).
- `PermissionScope`: explicit scope type and ID plus owner/project boundary where relevant.
- `AccessRequest`: subject + resource + operation + scope + request/trace ID + declared sensitivity and destination metadata.
- `PermissionDecision`: allow/deny/approval-required, stable reason code, matched grant/policy reference, and decision timestamp.
- `PermissionGrant`: explicit subject/resource/operation/scope constraints, issuer, created/expiry/revocation metadata, and optional conditions.
- `ApprovalRequest`: immutable summary/hash of the exact proposed action, requester, target, risk class, expiry, and status.
- `ToolDefinition`: stable ID/version, input/output schemas, handler boundary, required operation/resource mapping, risk class, timeout, and size limits.
- `ToolCallRequest` / `ToolExecutionResult`: validated, typed request and normalized result; no raw handler exception or secret-bearing payload.
- `AuditEvent`: append-only event type, actor, target, operation, decision/outcome, correlation ID, timestamp, and redacted metadata.

Do not use free-form strings as the only authorization boundary. Validate enum-like values and lengths at the service edge.

## 6. Work packages and execution order

### WP-5.1 — Security Audit, Threat Model & Contracts

- Audit all current API/service entry points that read or mutate conversations, profiles, and memories.
- Inventory existing tool-like execution, filesystem access, provider credential handling, and any direct subprocess/network boundaries.
- Define trust boundaries, threat scenarios, denial reason codes, operation vocabulary, and typed public contracts.
- Reconcile `docs/PERMISSIONS.md`, `docs/AGENT_RUNTIME.md`, and `docs/AI_ORCHESTRATION.md` with the accepted Phase 5 boundary.
- Add contract validation tests and document unsupported resource domains.

**Exit:** threat model and contracts are explicit; no implementation claims exceed existing application capabilities.

### WP-5.2 — Permission Registry & Policy Engine

- Implement PermissionManager and a deterministic policy evaluator.
- Implement explicit grants, exact subject/resource/operation/scope matching, expiry, revocation, and conditions.
- Deny by default; reject wildcard/inferred scope expansion and unknown operation/resource types.
- Keep policy evaluation independent from LLM/provider calls.
- Provide a narrow policy interface for domain services and tests.
- Add repository/storage support for grant records only where the existing storage lifecycle supports it; keep authorization logic out of repositories.

**Exit:** positive grants authorize only the exact matching tuple; cross-owner, cross-scope, expired, revoked, malformed, and unknown requests are denied.

**WP-5.2 implementation status (2026-11-24):** Added typed exact-scope permission grant persistence (`permission_grants`), `PermissionRepository`, and a deterministic `PermissionManager`. The manager denies when storage is absent, storage errors, or no exact active grant matches. Grant issuance/revocation is independently default-deny through `GrantAdministrationPolicy`; agent-type and agent-run subjects are explicitly barred from grant administration. Expiry and revocation are evaluated using timezone-aware UTC timestamps. The additive table is created through the current SQLAlchemy metadata initialization; this is not a versioned migration framework. GitHub Actions passed 161 tests, Python compilation, and frontend syntax validation after correcting the repository import cycle and updating the schema-baseline test.

### WP-5.3 — Approval & Audit Services

- Implement one-time approval requests bound to the exact action payload hash, actor, resource, operation, and expiry.
- Support pending, approved, rejected, expired, and consumed states; prevent replay and approval reuse.
- Require approval for destructive or externally visible operations according to risk policy.
- Add append-only audit recording for requests, decisions, approval transitions, executions, and failures.
- Redact credentials, tokens, private content, and raw exception data before persistence or display.

**Exit:** approval cannot be replayed or transferred to a different action; audit records explain decisions without retaining secrets.

### WP-5.4 — Tool Registry & Contracts

- Implement a registry of explicitly registered, versioned tool definitions.
- Validate tool ID/version, input schema, output contract, operation mapping, timeout, and size limits.
- Treat model-generated tool calls as untrusted proposals.
- Reject unknown, disabled, malformed, over-limit, or unregistered tools before execution.
- Do not add shell, arbitrary Python, unrestricted filesystem, browser-control, or unrestricted network tools in this phase.

**Exit:** only registered tools with valid bounded schemas can reach the execution gateway.

### WP-5.5 — Bounded Tool Runtime & Gateway

- Implement ToolGateway/ToolRuntime as the only execution path for registered tools.
- Enforce the sequence: validate request → authorize → require/consume approval if applicable → execute within limits → normalize result → audit outcome.
- Use injected handlers and narrow typed capabilities; handlers must not receive the PermissionManager's persistence session or arbitrary repositories.
- Enforce timeouts, cancellation where supported, output-size limits, and safe exception normalization.
- A denied or failed action must not be silently retried through another tool.

**Exit:** direct handler invocation is not exposed as an application capability; every successful execution has a prior authorization decision and correlated audit event.

### WP-5.6 — Existing Domain Integration

- Integrate authorization checks at the application-service boundary for existing conversation/session/message and memory operations.
- Preserve MemoryService's current default-deny policy behavior; adapt it to the central PermissionManager without creating a permissive fallback.
- Integrate ContextManager only through explicit authorized scope resolution; context assembly must not broaden memory or conversation scope.
- Protect existing profile operations where an authenticated/explicit local subject can be represented safely.
- Add extension interfaces for Knowledge, managed files, provider credentials, and connectors, but mark them unavailable until their owning services exist.
- Do not pretend the current app has user authentication. Local application identity is not a hosted multi-user security boundary.

**Exit:** existing protected operations fail closed when no explicit application policy is configured; all integrated paths have allow/deny tests and no direct repository/session exposure to callers.

### WP-5.7 — Integration, Security Regression & Documentation

- Add end-to-end service-level tests for allowed, denied, expired, revoked, wrong-owner, wrong-scope, invalid-tool, approval-required, approval-replay, timeout, output-limit, and audit-redaction cases.
- Add regression tests for conversation, memory, storage, Interface Manager, and Local Model Runtime behavior.
- Update `PERMISSIONS.md`, `ARCHITECTURE.md`, `README.md`, `docs/README.md`, and `ROADMAP.md` to distinguish implemented from planned integration.
- Record schema additions and the migration limitation explicitly; do not claim versioned migration support unless it is implemented and tested.
- Run full CI-equivalent validation and inspect the final diff and PR checks.

**Exit:** all security invariants are covered by tests, full suite and syntax checks pass, docs match code, and unsupported future domains remain explicitly unavailable.

## 7. Required package layout (adapt after audit)

Proposed starting layout; adjust only when existing conventions justify it:

```text
core/
  permissions/
    __init__.py
    types.py
    policies.py
    manager.py
    grants.py
    approvals.py
    audit.py
  tools/
    __init__.py
    schemas.py
    registry.py
    gateway.py
    runtime.py
    errors.py
  repositories/
    permission_repository.py
    approval_repository.py
    audit_repository.py
tests/
  test_permission_contracts.py
  test_permission_manager.py
  test_approval_service.py
  test_permission_audit.py
  test_tool_registry.py
  test_tool_runtime.py
  test_permission_domain_integration.py
docs/
  PERMISSIONS.md
  TOOL_RUNTIME.md
  PHASE_05_EXECUTION_PLAN.md
```

This is a proposed organization, not a mandate to duplicate existing abstractions. Keep public contracts small and domain ownership clear.

## 8. Explicit non-goals

- Agent Runtime, agent lifecycle, autonomous planning, Supervisor, and multi-agent execution (Phases 6–9).
- General-purpose shell, arbitrary code execution, unrestricted browser/computer control, or unrestricted filesystem/network access.
- Automatic permission grants based on model confidence, prompt instructions, tool metadata, or agent declarations.
- Hosted multi-user authentication/authorization; current application authentication is not implemented.
- Claiming full Knowledge/file/connector protection before those services and their storage contracts exist.
- Encrypted credential vault implementation; Phase 5 may enforce access mediation/redaction seams but must not claim credentials are encrypted at rest.
- PostgreSQL deployment or completion of the outstanding Phase 4 WP-4.7 migration framework.
- Replacing StorageManager, repositories, or Phase 4 services.

## 9. Validation commands

Run from the project virtual environment:

```powershell
python -m pytest -q tests/test_permission_contracts.py tests/test_permission_manager.py
python -m pytest -q tests/test_approval_service.py tests/test_permission_audit.py
python -m pytest -q tests/test_tool_registry.py tests/test_tool_runtime.py
python -m pytest -q tests/test_permission_domain_integration.py
python -m pytest -q -W default
python -m compileall -q core main.py
node --check static/app.js
```

Run focused commands as their work packages land. At phase completion, record exact counts and actual command results. Do not claim tests were run unless their output is observed. Do not weaken or skip existing tests to obtain a green build.

## 10. Branch, commit, and PR protocol

- Use only `feat/phase-5-permission-manager-tool-runtime`, created directly from `main`.
- Keep all WP-5.1 through WP-5.7 work on this one branch and in one PR.
- Commit each work package separately with a conventional, descriptive message.
- Do not create a branch or PR from this feature branch.
- Do not create another PR while this PR is open.
- If the diff becomes too large to review safely or repository/CI constraints require a boundary, first complete and validate a coherent slice, merge its PR only after required checks pass, then create any continuation branch directly from the updated `main`.
- Do not merge merely to reduce the number of files; prefer one coherent phase PR.
- No PR merge is authorized by this execution plan. Merge only after checks pass and the user explicitly approves it.

## 11. Phase-wide acceptance criteria

Phase 5 is complete only when:
1. The PermissionManager is the central deterministic authorization decision point for every integrated protected operation.
2. Missing/invalid/expired/revoked/unsupported access is denied by default.
3. Grants are exact-scoped, revocable, and auditable.
4. Approval is one-time, action-bound, expiring, and replay-safe.
5. Tool calls are schema-validated and can execute only through the bounded Tool Runtime.
6. Every execution is preceded by authorization and correlated with redacted audit events.
7. Existing conversation and memory services are integrated without leaking persistence internals.
8. No agent/model can grant itself permissions or bypass the gateway.
9. Unsupported Knowledge/file/connector domains are explicitly marked unavailable rather than falsely certified.
10. Full regression, security tests, Python compilation, and frontend syntax checks pass.
11. README, architecture, roadmap, module contracts, execution plan, and implementation status agree.

## 12. Execution directive

**Project:** Local AI Assistant  
**Phase:** 5 of 11 — Tool Runtime & Permission Manager

**Mandatory instruction:** Execute this document in the order WP-5.1 through WP-5.7 on the single branch `feat/phase-5-permission-manager-tool-runtime`, created directly from `main`. Commit each completed work package separately and keep the complete phase in one pull request unless a documented review/CI constraint requires a validated merge boundary. Enforce default-deny authorization, explicit scope, no self-grant, one-time action-bound approvals, bounded tool execution, and redacted auditability. Do not expose database sessions, repositories, ORM entities, credentials, arbitrary code execution, or unrestricted system access to models or agents. Do not claim Knowledge/file/connector coverage, hosted authentication, encrypted credential storage, PostgreSQL support, or versioned migrations unless each is actually implemented and tested. This is the authoritative execution plan for Local AI Assistant, Phase 5; implementation and final completion status must be recorded against this exact phase and branch.
