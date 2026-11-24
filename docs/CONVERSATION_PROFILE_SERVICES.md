# Conversation & Profile Services

**Project:** Local AI Assistant  
**Phase:** 4 — Storage & Memory Services  
**Work package:** WP-4.4 — Conversation Storage integration  
**Status:** Implemented and locally validated (2026-11-24)  
**Branch:** `feat/storage-memory-services`

## Ownership

- `ConversationService` owns session workflows, message-history retrieval, title rules, and chat-turn persistence orchestration.
- `ProfileService` owns profile validation/serialization and avatar normalization and lifecycle.
- `SessionRepository`, `MessageRepository`, and `ProfileRepository` remain the only persistence adapters used by these services.
- FastAPI routes translate service errors into HTTP responses and handle transport concerns. They do not issue direct conversation/profile ORM queries or commits.

## Conversation behavior

- New sessions retain the default title `گفتگوی جدید`.
- Session listing is ordered by creation time descending, then ID descending.
- Message history is returned in ascending message-ID order.
- A first user turn auto-generates a title from the first 35 characters plus an ellipsis when needed.
- A custom title is never overwritten by automatic chat-title generation.
- User messages are committed before provider inference begins.
- Assistant messages are committed only after the provider stream completes successfully.
- Failed inference preserves the user message but does not create an assistant message.
- Session deletion continues to rely on the existing ORM cascade for its messages.

## Profile behavior

- The single local profile retains its existing default identity fields.
- Display name and username are trimmed and required; email validation preserves the existing lightweight validation rule.
- Avatar upload remains limited to 2 MiB and PNG/JPEG/WebP input.
- Images larger than 4096×4096 are rejected and accepted images are normalized to 256×256 WebP.
- Avatar retrieval retains `Cache-Control: no-store`; missing avatars return HTTP 404.

## API compatibility

The existing endpoint paths, request models, response field names, and success/error status behavior are retained. No schema or migration changes are included in WP-4.4.

## Validation

Run:

```powershell
python -m pytest -q tests/test_conversation_profile_services.py tests/test_profile_api.py tests/test_sessions_api.py
python -m pytest -q -W default
python -m compileall -q core main.py
node --check static/app.js
```

WP-4.4 local validation passed: 13 focused service/API tests, 124 total tests, Python compilation, and frontend JavaScript syntax check.
