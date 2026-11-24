# Context Manager

**Project:** Local AI Assistant  
**Phase:** 4 of 11 — Storage & Memory Services  
**Work package:** WP-4.6 — Context Manager  
**Status:** Implemented; local validation pending  
**Branch:** feat/phase-4-context-manager (stacked on feat/phase-4-memory-service)

## 1. Responsibility

Context Manager assembles a request-scoped package from explicitly selected conversation history and memory scopes. It is not a persistent store and does not create or promote memories. Its output is typed, bounded, and traceable to the source records.

The current implementation has two sources:
- Recent conversation messages through ConversationService.
- Memory records through MemoryService, but only for MemoryScope values explicitly supplied by the caller.

Knowledge retrieval is intentionally not connected until the Knowledge Storage contract is delivered in WP-4.7. The package reports knowledge_status=not_connected; it does not pretend that knowledge retrieval occurred.

## 2. Public contracts

- ContextRequest identifies the conversation, current query, owner, history/memory limits, token budget, explicit memory scopes, and whether candidate memories may be considered.
- ContextItem contains source type/reference, content, relevance score, trust status, provenance, and optional message role/model/timestamp.
- ContextPackage returns selected items, estimated token use, configured budget, omitted-item count, and knowledge-source status.

The current query is passed separately and is not duplicated into historical context. If the same current user turn has already been persisted as the latest message, that final duplicate is excluded from history.

## 3. Source access and trust

Conversation access is performed only through ConversationService. A bounded repository query returns the latest N messages and restores chronological order before presentation. Each message retains its stable message ID, model label, and timestamp.

Memory access is performed only through the injected MemoryService. The caller must pass an explicit tuple of MemoryScope values; the manager never guesses, broadens, or automatically adds user/global/conversation scopes. Every scope owner must match the request owner. MemoryService access policy remains authoritative, including its default-deny behavior. Candidate memories remain excluded unless include_candidates is explicitly enabled.

Conversation history is marked historical_unverified. Memory items preserve lifecycle status, reviewer identity, source metadata, and original provenance. An active memory is eligible for context but retrieval is not represented as proof that its content is current or universally correct.

Exact normalized duplicate content is included once. When a memory and conversation item are exact duplicates, the memory item is retained so its lifecycle and provenance remain visible.

## 4. Ranking and budget

Memory candidates use the deterministic score returned by MemoryService. Conversation messages receive a deterministic recency score, with newer messages preferred for budget selection. Ties are stable and prefer memory provenance.

The default budget estimator uses a conservative character-based approximation (three characters per estimated token) plus 12 tokens of per-item overhead. This is not a model tokenizer and must not be described as an exact token count. The configured budget is enforced before returning the package; over-budget items are omitted whole rather than silently truncated. The result reports estimated_tokens and omitted_items.

Presentation order is memory first (highest score first), followed by selected conversation messages in chronological order.

## 5. Security and phase boundaries

- No database session, ORM entity, repository, or arbitrary query object is exposed by Context Manager.
- No memory scope is inferred from a conversation ID or owner ID.
- No candidate memory is included by default.
- No cloud-provider dispatch or external transmission occurs in this package.
- No Knowledge Storage adapter is added before WP-4.7.
- This package is an integration seam, not the Phase 5 Permission Manager. Protected knowledge/file/tool access remains unavailable until its owning authorization contract exists.

## 6. Validation

Run locally:

```powershell
python -m pytest -q tests/test_context_manager.py tests/test_conversation_profile_services.py tests/test_memory_service.py
python -m pytest -q -W default
python -m compileall -q core main.py
node --check static/app.js
```

Record the exact focused and full-suite counts. CI success alone does not replace local validation.

## 7. Execution directive

**Project:** Local AI Assistant  
**Phase:** 4 of 11 — Storage & Memory Services  
**Work package:** WP-4.6 — Context Manager

**Mandatory instruction:** This document governs WP-4.6 for Local AI Assistant, Phase 4. Implement only request-scoped assembly from authorized conversation history and explicitly scoped Memory Service results. Preserve provenance, default-deny memory access, candidate exclusion, and deterministic budget enforcement. Do not invent Knowledge Storage results, silently widen scopes, persist assembled context as memory, or implement Phase 5 permissions here. Mark this work package complete only after focused tests, the full suite, Python compilation, and frontend syntax validation have passed and the exact evidence is recorded.
