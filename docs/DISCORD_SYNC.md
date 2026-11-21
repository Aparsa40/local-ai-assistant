# Discord Synchronization

**Status:** Optional future connector; not part of the core runtime dependency chain.

## 1. Purpose

Discord synchronization may publish selected project status and approved context to a Discord server/channel so project progress can be monitored and retrieved. Discord is a presentation/synchronization endpoint, not the source of truth.

The application's local database and managed project files remain canonical.

## 2. Scope

Potential use cases:
- publish approved project status summaries;
- publish roadmap milestones and implementation state;
- share selected release/PR/CI status;
- post Librarian reports only when the user explicitly approves sharing;
- link back to canonical repository files or application records.

Do not mirror all conversations, model-private memories, credentials, or source archives by default.

## 3. Permission model

- User explicitly connects the Discord bot/account.
- User selects server, channel, projects, and data categories.
- Read and write scopes are separate.
- Publishing a report to Approved Knowledge does not automatically authorize publishing it to Discord.
- Sensitive or destructive Discord actions require explicit confirmation.
- Revocation stops future synchronization; previously posted messages are governed by a separate retention/removal policy.

## 4. Sync direction and conflict policy

Each sync job must declare direction:
- application -> Discord;
- Discord -> application;
- bidirectional only when a concrete use case and conflict policy are approved.

For project status publishing, application -> Discord is the preferred initial scope. Discord edits must not silently overwrite canonical application data.

Use stable external message/channel identifiers, idempotency keys, timestamps, and sync checkpoints. Detect edits/deletions and surface conflicts rather than silently overwriting local records.

## 5. Operational behavior

- Handle Discord rate limits and transient failures with bounded retries.
- Queue pending updates locally when Discord is unavailable.
- Show last successful sync, pending work, and failures.
- Avoid duplicate messages on retry.
- Keep bot tokens in the credential boundary and never log them.

## 6. Acceptance criteria for a future implementation

- Connector can be disconnected without affecting local project data.
- Only selected channels and approved data categories are synchronized.
- Each outbound message has provenance to the source record/version.
- Repeated sync runs do not create duplicates.
- Failures and rate limits are visible and recoverable.
- Discord content is treated as untrusted input if imported.

Related: [CONNECTOR_SYSTEM.md](CONNECTOR_SYSTEM.md), [PERMISSIONS.md](PERMISSIONS.md), [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md).
