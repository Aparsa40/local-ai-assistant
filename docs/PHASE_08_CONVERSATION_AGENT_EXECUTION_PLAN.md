# Phase 8 — Conversation Agent

**Project:** Local AI Assistant  
**Phase:** 8 of 11  
**Document type:** Authoritative execution and acceptance contract  
**Status:** Implementation remains under review on branch `feat/phase-8-conversation-agent`; PR #23 is open and not merged. The latest verified revision `eafe9096c19fe1b77c39662a28c9a441587d8adc` passes 475 Python tests, Python compilation, and JavaScript syntax validation in GitHub Actions run `45702444215`; the existing FastAPI TestClient chat smoke tests also pass. Durable request identity/event replay and interrupted-operation recovery are implemented through migration `0007_conversation_operations`; delegated Phase 7 cancellation propagation is also implemented. Phase 8 is **not yet complete**: delegated Agent Runtime tool approvals now emit an actionable `approval_required` SSE event and resume the same child run after an authorized decision; permission-driven memory/knowledge context approvals now use request-bound, action-hash-bound one-time approval tokens and resume context assembly only after an authorized decision. The deterministic workflow registry is intentionally empty and routes are denied until owning services register workflows; model-assisted classification is supported but disabled by default. A real local loopback-server smoke run is still outstanding. Do not merge or mark the phase complete until the remaining acceptance gaps are resolved or explicitly accepted as deferred.  
**Dependencies:** Phases 4–6 completed; Phase 7 merged via PR #21  
**Last reviewed:** 2026-11-25

## Current implementation verification (2026-11-25)

Latest verified branch head: `eafe9096c19fe1b77c39662a28c9a441587d8adc`.

- GitHub Actions: successful.
- Python suite: 475 passed in 23.94s (GitHub Actions run `45702444215`).
- `python -m compileall -q core main.py`: successful in CI.
- `node --check static/app.js`: successful in CI.
- FastAPI TestClient smoke test: direct chat SSE lifecycle, durable operation registry, and assistant-message persistence verified.
- Durable operation migration `0007_conversation_operations` persists request hashes, safe lifecycle events and terminal outcomes; interrupted in-flight work is marked uncertain and is never automatically replayed.
- Focused regression coverage includes immediate SSE disconnect/retry, same-key conflict, restart replay/recovery, trusted scope ownership, boolean authorization flags, classifier failure, offline readiness, UI cancellation/retry, Phase 7 cancellation propagation, delegated approval event/redaction, same-child-run continuation, owner-checked idempotent plan resume, and request-bound memory/knowledge approval creation, decision, one-time consumption and context reassembly.

Outstanding acceptance gaps:
1. Deterministic workflow registry is empty; routes remain denied until owning services register real workflows.
3. Model-assisted classification remains optional and disabled by default.
4. A real loopback server smoke run in the target local environment; CI currently uses FastAPI TestClient rather than launching the user's local server.

## 1. Purpose

Replace the manual-provider-oriented POST /api/chat workflow with a controlled, auditable Conversation Processing lifecycle. The system accepts a user turn, establishes request identity and policy context, classifies the work, retrieves only authorized context, selects a permitted execution path, validates the result, streams safe progress, and persists a truthful final outcome.

The Conversation Agent is the user-facing workflow agent hosted by the existing Phase 6 Agent Runtime. It is not a second runtime, provider router, permission engine, database owner, or tool executor.

## 2. Phase boundaries and dependencies

Reuse:
- Phase 4: ConversationService, repositories, storage/migration infrastructure, ContextManager, memory and knowledge persistence.
- Phase 5: PermissionManager, exact-scope grants, approval workflow, ToolRegistry and ToolRuntime.
- Phase 6: Agent Runtime contracts, registry, lifecycle, controller, checkpoints, budgets, events and scoped execution.
- Phase 7: the merged Supervisor/OrchestrationService, goal/plan/task contracts, bounded sequential scheduling, handoffs, aggregation, cancellation and reconciliation.

Phase 7 was merged in PR #21 (merge commit c66b2d6acaa359899a26e3dac3aa424b0c33d8a5). Phase 8 may submit a compound goal to the existing orchestration service, but must not replace its scheduler or create a parallel orchestration engine.

Phase 8 owns user-turn intake, normalized conversation lifecycle, deterministic dispatch, explicit context and egress authorization, normalized response candidates, validation/composition, safe streaming, cancellation/retry semantics, durable outcomes, UI controls and conversation-level provenance.

Explicitly deferred:
- Phase 9: broader multi-agent collaboration, parallel fan-out, agent teams and advanced coordination.
- Phase 10: AI Librarian.
- Phase 11: backup, maintenance and external integrations.
- No provider adapter replacement, credential-vault project, hosted authentication, or broad refactor is part of Phase 8.

## 3. Current baseline — verify before changing

The current chat route is in main.py. It prepares/persists the user turn through ConversationService.prepare_chat(...), assembles bounded context through ContextManager (history-oriented; memory scopes are not implicitly enabled), uses core/orchestrator.py for provider/model message preparation, streams through InterfaceManager.stream_chat(...), and persists the assistant message after successful streaming.

Agent Runtime and orchestration APIs also exist. These HTTP endpoints are application boundaries, not internal service interfaces. Conversation Agent must call application services through dependency injection/composition roots; it must not make loopback HTTP requests back into its own API.

Inspect the actual merged main code and tests before implementation. Treat this section as a baseline to verify, not permission to assume signatures or invent missing services. Record discrepancies in the PR and update this plan if contracts materially differ.

## 4. Non-negotiable invariants

1. One owner per responsibility. Reuse existing services and repositories; do not duplicate persistence, context retrieval, permissions, tool execution, agent lifecycle or orchestration.
2. Default deny. A classifier, prompt, model, intent label or user wording never creates a permission or grant.
3. No implicit cloud egress. Local/private context must not reach a cloud provider unless existing application policy explicitly authorizes that destination and data scope. If authorization is absent or ambiguous, do not transmit; ask, use an eligible local path, or stop clearly.
4. Model output is untrusted. Classification, plans, tool proposals, evidence references and candidate responses require application-side validation.
5. Bounded execution. Enforce request, token, wall-clock, tool-call, output-size, retry and delegation limits using existing budget mechanisms.
6. No unbounded autonomous loop. A turn may delegate a bounded goal; it may not recursively plan or call tools without limits and stop conditions.
7. No false success. Partial, blocked, failed, rejected or uncertain execution remains distinguishable from success.
8. No duplicate side effects. Retries, disconnects and recovery must not blindly replay non-idempotent actions.
9. No hidden reasoning leakage. Never stream or persist private chain-of-thought; persist only safe status, concise progress, structured decisions and user-facing output.
10. Preserve sessions, messages, titles, provider/model selection, credentials and settings.

## 5. Canonical contracts

Define versioned, validated contracts in the project's established style. Names below are semantic requirements, not mandatory class names.

### 5.1 ConversationRequest
Include schema_version, request_id (client idempotency key or server-generated stable ID), conversation/session identity, normalized user message, validated attachments/references if supported, user-selected provider/model preferences, requested mode/preferences if exposed, timestamp and safe client metadata. The principal must come from the existing application security boundary, never from a request-body field.

### 5.2 DispatchDecision
Use a closed enum: direct_response, deterministic_workflow, agent_delegation, needs_user_input, blocked. Include reason codes, required capabilities, explicit data scopes, destination class, execution budget and approval requirement.

Apply deterministic rules and policy checks first. An optional model-assisted classifier may propose a schema-constrained label; validate it and fall back deterministically on malformed output, timeout or model unavailability. A classifier cannot select an unauthorized destination or widen scope.

### 5.3 ResponseCandidate and ValidationReport
Candidate semantics include normalized content, execution status, provenance references, tool/run outcomes and declared limitations.

Validation report includes valid/partial/rejected status; schema and required-section results; evidence/reference existence checks; required-task coverage and delegated run terminal state; tool outcome and side-effect uncertainty; policy/scope/egress compliance; machine-readable issue codes and safe explanations.

Reference existence is not proof of factual correctness. Distinguish source-backed evidence from generated statements. Never fabricate citations, tool success or completion.

### 5.4 Provenance
Correlate conversation/session, request, assistant message, provider/model invocation, orchestration goal/plan, agent run and event IDs where available. Record only safe metadata: provider/model IDs, execution mode, route/reason code, timestamps, usage if available, status, source references and error codes. Never log credentials, full private prompts, unredacted context or hidden reasoning.

## 6. Deterministic dispatch policy

Keep the first implementation conservative and testable.

| Request class | Route | Rule |
|---|---|---|
| Ordinary question not requiring tools/delegation | Direct response | Use user-selected eligible provider/model and permitted context |
| Fixed application operation with deterministic service contract | Deterministic workflow | Call the owning service; do not invent an agent for ordinary CRUD |
| Compound bounded goal requiring registered agents | Agent delegation | Submit scoped goal to existing OrchestrationService/Supervisor |
| Missing scope, ambiguous destructive intent, unavailable capability or approval requirement | Needs input / blocked | Ask, obtain existing approval or stop safely |

Dispatch thresholds and rules must be explicit in code and tests. Do not invent arbitrary complexity scores. Model classification is advisory only and cannot bypass guardrails.

### Supervisor handoff
- Create goals through the existing application service/composition root, not HTTP calls to the app's own endpoints.
- Child scopes must be subsets of the authorized request scope.
- Preserve request/conversation correlation IDs in supported metadata or a versioned handoff envelope.
- Pass explicit goal, acceptance criteria, budget and cancellation linkage.
- Validate persisted plan/run/aggregate results before composing a response.
- Paused, failed, incomplete or unavailable orchestration remains visible as such.
- Do not add multi-agent fan-out or parallel scheduling in Phase 8.

## 7. Context, privacy and execution strategies

### Context
Use ContextManager and existing permission-aware services. Explicitly specify conversation history, memory scopes and knowledge scopes. Empty/omitted scopes remain empty; do not enable all memories or knowledge by default.

Separate retrieval authorization from destination/egress authorization. Permission to read local material does not imply permission to transmit it to a cloud provider. Check both before transmission and ensure sensitive content never enters provider payloads before authorization succeeds.

### Shared online/offline contract
Both strategies accept the same normalized request/context and return the same normalized candidate/result shape. Both invoke models only through InterfaceManager; no provider SDK calls from Conversation Agent or route handlers.

- Online: eligible cloud provider through InterfaceManager, only after explicit destination authorization for every transmitted data scope.
- Offline: eligible local provider through InterfaceManager, only when local runtime/provider readiness and model capability are evidenced.
- Preserve user-selected provider/model by default.
- Fallback must re-check capability, context window, modality, tool support, health and destination policy. Never assume models are interchangeable.
- Disclose material fallback/capability changes.
- If no eligible route exists, pause, ask the user or report a clear limitation. Never silently switch to an unauthorized cloud destination or claim reasoning occurred without a model.

Do not build a speculative autonomous router. Implement only routing required by actual providers and InterfaceManager contracts.

## 8. Streaming, persistence, cancellation and idempotency

### Event protocol
Define a versioned SSE envelope with stable event_id, request_id, conversation_id, timestamp, event type and bounded payload. Minimum event types:
- accepted
- status
- progress
- candidate (optional, clearly non-final)
- validation
- approval_required
- final
- error
- cancelled

Never emit internal prompts, hidden reasoning, credentials, raw exception strings, raw context or unredacted tool output.

### Persistence
- Validate request and establish idempotency identity before inference.
- Persist the user turn once using ConversationService semantics.
- Persist lifecycle/provenance events through an appropriate existing service; add a migration only if existing tables cannot safely represent required durable state.
- Persist assistant final only after validation/composition reaches an allowed terminal result.
- Partial output must not masquerade as a completed assistant message.
- Preserve session title and fresh-chat semantics.
- Keep errors/cancellation traceable without corrupting history.

### Idempotency and disconnect
Define a uniqueness boundary for a request within a conversation. Repeated requests with the same key must return/reconcile the existing operation, not create duplicate turns or side effects.

Specify behavior for duplicate submission while running, retry after completion, browser disconnect, explicit cancellation, server restart, assistant persistence failure after provider completion and uncertain tool side effects.

Use existing Agent Runtime/Orchestration recovery for delegated work. Never blindly rerun non-idempotent tools. If safe recovery is impossible, mark the operation uncertain and require explicit user action. Cancellation propagates to owned runs when supported. An SSE disconnect alone is not proof of cancellation.

## 9. UI integration

Preserve existing chat UX and settings. Add only supported controls/status:
- visible execution status and safe progress;
- execution mode and provider/model actually used;
- explicit fallback disclosure;
- approval handoff through existing approval mechanism;
- cancel and safe retry;
- partial/blocked/failed state distinct from success.

Do not add controls implying unsupported pause/resume or arbitrary routing. Reconnect must not duplicate messages or execution.

## 10. Work packages

### WP-8.0 — Baseline audit and contract freeze
Inspect merged main, PR #21 implementation, service constructors, repositories, SSE, UI and tests. Map behaviors to existing services and identify only minimal missing seams. Document discrepancies and a file-level plan before coding.
**Exit:** baseline map, composition design, privacy/data-flow review and implementation plan in PR.

### WP-8.1 — Contracts and request identity
Add versioned request, dispatch, candidate, validation, provenance and event contracts. Define idempotency and compatibility.
**Exit:** tests cover valid, invalid, oversized and incompatible payloads.

### WP-8.2 — Conversation service and deterministic dispatcher
Implement conservative dispatch. Model-assisted classification, if justified, is optional/advisory with strict schema and deterministic fallback.
**Exit:** table-driven tests prove routing, classifier fallback and no permission escalation.

### WP-8.3 — Context authorization and strategies
Integrate ContextManager, PermissionManager and InterfaceManager. Implement only supported online/offline strategies. Enforce destination authorization before cloud egress.
**Exit:** fake-provider tests prove normalized contract parity, routing policy, fail-closed behavior and zero unauthorized private-context transmission.

### WP-8.4 — Supervisor/Agent Runtime delegation
Integrate through existing OrchestrationService composition root. Define correlation, scoped handoff, budgets, cancellation and aggregate mapping. No internal HTTP calls and no Phase 9 features.

Phase 7 compatibility seam: after an approval has been decided, the existing Agent Runtime approval flow must clear the pending approval and execute the same child run. The owning plan can then be continued through the public owner-checked `OrchestrationService.resume_plan(plan_id, run_id, owner_id)` contract. The scheduler verifies plan/run ownership and terminal child state, maps that persisted outcome once, and schedules only remaining pending nodes. It never restarts the child run or automatically retries a failed child after this explicit approval continuation. If the bounded conversation approval wait expires, the owning plan and paused child are cancelled. This seam does not itself implement the Conversation Agent's approval SSE/UI continuation.

**Exit:** tests cover direct/delegated decisions, scope containment, successful/partial/failed orchestration, cancellation, unavailable Supervisor, and explicit child-run approval resumption without duplicate execution.

### WP-8.5 — Response validation and composition
Implement schema, reference, task coverage, tool outcome and policy validation; compose truthful final/partial/blocked responses.
**Exit:** false-success, missing-reference, malformed-candidate and uncertain-side-effect cases are rejected or partial.

### WP-8.6 — Streaming, persistence and UI migration
Integrate versioned SSE, idempotency, durable outcomes, cancellation, reconnect and UI state. Preserve API compatibility where practical; document intentional changes.
**Exit:** disconnect/retry/restart tests prove no duplicate messages or side effects.

### WP-8.7 — Security, regression and delivery
Run focused tests throughout, then one full Python suite at the end, frontend syntax checks and loopback smoke tests. Update affected docs and prepare one PR.
**Exit:** acceptance checklist is evidenced by tests and CI; no merge.

## 11. Suggested module map (not mandatory)

Prefer extending existing services. Add core/conversation_agent only if it creates a genuine cohesive boundary:

~~~text
core/conversation_agent/
  contracts.py
  analyzer.py
  dispatcher.py
  strategies/
    base.py
    online.py
    offline.py
  validator.py
  composer.py
  service.py
~~~

Potential integration points: main.py, core/orchestrator.py (compatibility facade only if needed), core/conversations/, core/context/, core/agents/, core/orchestration/, core/interface_manager.py, static/ and tests/.

Do not create every suggested file automatically. Keep modules minimal and consistent with project conventions.

## 12. Test strategy and required validation

Focused tests during implementation:
- request schema, ID generation, duplicate submission and compatibility;
- deterministic dispatch and classifier failure;
- context scopes, permission denial and destination/egress denial;
- cloud adapter receives no private context without explicit authorization;
- offline readiness and model capability fallback;
- provider/model selection preservation and visible fallback;
- Supervisor handoff, scope containment, correlation and aggregate statuses;
- validator schema, evidence references, missing tasks and tool outcomes;
- SSE event ordering, payload redaction and no hidden reasoning;
- cancellation, disconnect, retry, restart recovery and persistence failures;
- UI state and legacy chat regression.

Use fake providers/agents and deterministic clocks/IDs where practical. No live cloud credentials or hardware-intensive model loading in CI.

Final validation (once per phase, after focused tests):

~~~powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
~~~

Also run loopback HTTP smoke tests for direct chat, deterministic delegated chat fixtures, SSE final/error/cancel behavior and persistence across restart. Report exact commands, counts, warnings and environment limitations. Do not repeat the full suite after every small change.

## 13. Phase-wide acceptance checklist

- [x] Sessions, messages, titles, provider/model settings and credentials remain intact.
- [x] Conversation Agent reuses Agent Runtime; no second runtime.
- [x] Direct, deterministic and delegated paths share normalized request/result/provenance contracts.
- [x] Dispatch is deterministic, bounded, explainable and tested.
- [x] Classification cannot grant permissions, widen scopes or select unauthorized egress.
- [x] Context scopes are explicit; memory/knowledge are not implicitly enabled.
- [x] Cloud transmission is denied unless destination authorization covers the data.
- [ ] Online/offline paths use InterfaceManager and re-check all model capability constraints; readiness is covered, but complete capability-parity evidence remains.
- [x] User-selected provider/model is preserved; any configured fallback is gated and disclosed (no cloud fallback is enabled by default).
- [x] Supervisor handoff uses internal composition, existing Phase 7 contracts and bounded scopes.
- [x] Phase 9 multi-agent enhancements are not introduced.
- [x] Validator distinguishes valid, partial and rejected; never fabricates evidence.
- [x] Streaming never exposes hidden reasoning, secrets, raw exceptions or private context.
- [x] Durable idempotency, cancellation, disconnect and restart recovery prevent automatic duplicate execution.
- [x] Delegated Agent Runtime tool approvals emit a redacted `approval_required` event; the UI can approve/reject through existing endpoints and resumes the same child run before the plan continues.
- [x] Permission-driven memory/knowledge context approvals use the same request-bound SSE and existing approval workflow; the exact approved access request is consumed once before context retrieval continues.
- [x] CI full suite and JavaScript syntax pass (475 Python tests); FastAPI TestClient smoke passes.
- [ ] A real loopback-server smoke run remains outstanding.
- [x] README, roadmap, architecture, AI orchestration, docs index, changelog and this plan agree on current Phase 8 status and open gaps.
- [x] One implementation PR is open for review and has not been merged.

## 14. Execution directive

Implement Phase 8 only, on a dedicated branch named feat/phase-8-conversation-agent created from the then-current main. The documentation-preparation branch is not the implementation branch.

Before coding, verify that the documentation-preparation PR has merged and branch from updated main. If it has not merged, stop and report the dependency rather than implementing against stale contracts.

Execute WP-8.0 through WP-8.7 in order. Commit coherent milestones on that one branch. Do not create additional phase branches or combine Phase 9/10/11 work. Do not alter main directly. Do not merge the PR. If acceptance cannot be met, open a PR only when remaining gaps are explicit and safe; otherwise report the blocker without claiming completion.
