# Phase 8 — Conversation Agent

**Project:** Local AI Assistant  
**Phase:** 8 of 11  
**Document type:** Authoritative execution plan  
**Status:** Planned — execution contract prepared; current chat remains manual-provider oriented  
**Dependencies:** Phases 4–6; Phase 7 integration for complex task delegation  
**Last reviewed:** 2026-11-24

## 1. Purpose and boundary

Replace the current manual-provider-oriented chat workflow with a controlled Conversation Processing layer. It receives user requests, resolves authorized context, chooses direct response versus deterministic workflow or agent delegation, invokes online/offline strategies through InterfaceManager, validates candidate output, and records conversation provenance.

Conversation Agent is the user-facing workflow agent hosted by Agent Runtime. It does not own provider adapters, database internals, permission policy, or tool execution.

## 2. Current baseline and reuse

Current chat/API/UI live in `main.py`, `core/orchestrator.py`, and `static/`. Reuse `ConversationService`, `ContextManager`, `PermissionManager`, `ToolRuntime`, `Agent Runtime`, and `InterfaceManager`. Do not duplicate session/message persistence or call provider SDKs from route handlers.

## 3. Scope

- Request envelope and conversation event lifecycle.
- Intent/request classification with deterministic fallback.
- Direct response, deterministic service workflow, or Agent Runtime task dispatch.
- Online and offline execution strategies using the same provider-neutral contract.
- Authorized context assembly and explicit destination/privacy policy.
- Response Validator & Composer for structure, evidence, completeness, and safety.
- Streaming response events with durable final message persistence.
- Provider/model/task/tool provenance and user-visible partial/failure states.
- Explicit fallback policy with no private-context cloud egress.

## 4. Work packages

### WP-8.1 — Request and conversation contracts
Define normalized request, intent, execution mode, response candidate, validation report, conversation event, and provenance envelopes. Preserve existing session/message IDs and current fresh-chat behavior.
**Exit:** request and response contracts are versioned and backward compatible.

### WP-8.2 — Request analyzer and dispatcher
1. Implement deterministic rules for direct response vs task delegation.
2. Add model-assisted classification only as a proposal with strict schema and fallback.
3. Resolve required capabilities, scopes, privacy, and output expectations.
4. Route tasks to Agent Runtime/Supervisor only when the request warrants it.
5. Never infer permission from intent or user phrasing alone.
**Exit:** dispatch decisions are explainable and cannot grant access.

### WP-8.3 — Context and execution strategy
1. Build context through ContextManager with explicit conversation/memory/knowledge scopes.
2. Enforce owner, sensitivity, destination, and permission checks before retrieval/transmission.
3. Implement online strategy via InterfaceManager.
4. Implement offline strategy via InterfaceManager and local runtime readiness evidence.
5. Re-check model capability/context limits after a fallback.
6. Pause/report if no eligible execution path exists.
**Exit:** both strategies use the same contract and private context is never silently sent to cloud.

### WP-8.4 — Response Validator & Composer
1. Validate output schema and required fields.
2. Verify tool outcomes and cited source references exist.
3. Detect missing sections, unsupported claims, and unresolved errors.
4. Distinguish generated content from verified source evidence.
5. Reject false success when an agent/tool failed or had uncertain side effects.
6. Compose a user-readable response without dropping material limitations.
**Exit:** candidate output cannot be marked complete without passing validation.

### WP-8.5 — Streaming and persistence integration
1. Stream normalized events (analysis state, progress, candidate, validation, final) without exposing hidden reasoning.
2. Persist user message before inference and assistant final only after validated completion.
3. Persist safe execution provenance and failures.
4. Support cancellation and disconnected clients without duplicate assistant messages.
5. Preserve existing session title and history semantics.
**Exit:** reconnect/retry does not corrupt chat history or duplicate side effects.

### WP-8.6 — UI integration and migration
1. Add online/offline execution state and task progress to chat UI.
2. Show provider/model changes and fallback disclosure.
3. Show approval requests and allow explicit user decision.
4. Provide clear pause/cancel/retry controls with safe idempotency.
5. Keep settings/provider selection as user-controlled configuration.
**Exit:** user can understand and control execution state.

### WP-8.7 — Security, evaluation, and delivery
Test prompt injection, context leakage, permission denials, model unavailability, malformed model output, invalid references, partial tool failure, uncertain side effects, stream disconnect, and persistence recovery. Update AI_ORCHESTRATION, ARCHITECTURE, README, and roadmap; deliver one PR after checks pass.

## 5. Suggested implementation map

```text
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
core/orchestrator.py  # compatibility facade or migrated entry point
main.py
static/
tests/
  test_conversation_dispatch.py
  test_execution_strategies.py
  test_response_validation.py
  test_conversation_events.py
  test_chat_security.py
```

## 6. Required validation

```powershell
python -m compileall -q core main.py
python -m pytest -q
node --check static/app.js
```

Use fake providers for deterministic CI, then a loopback HTTP smoke test. Include explicit online/offline tests and verify that a private scope cannot reach a cloud adapter without destination authorization.

## 7. Phase-wide acceptance

- Current chat behavior is migrated without losing sessions/messages or provider/model settings.
- Request classification and dispatch are deterministic, bounded, and auditable.
- Direct response and agent task paths share one normalized execution contract.
- Online/offline strategies are provider-neutral and re-check capabilities.
- Context retrieval and egress are permission checked.
- Response Validator reports evidence, gaps, and tool outcome status.
- Streaming, cancellation, and persistence are restart-safe and idempotent.
- No private local context is transmitted implicitly to a cloud provider.
- Full regression and documentation checks pass.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 8 of 11 — Conversation Agent

Execute WP-8.1 through WP-8.7 after its dependencies are accepted. Preserve existing user data and provider/model selection. Do not turn the current chat route into an unbounded autonomous agent loop.
