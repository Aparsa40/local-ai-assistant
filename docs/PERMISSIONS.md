# Permissions and Tool Safety

**Status:** Accepted target architecture; centralized Permission Manager and Tool Runtime are not implemented.

## 1. Security model
Default deny. An Agent, model, provider, or tool definition cannot grant permissions. Only application-side policy code and explicit user approvals can authorize protected actions.

## 2. Permission decision dimensions
Every protected operation should be evaluated against:
- subject: user, module, agent type, or specific agent run;
- resource: file, conversation, memory scope, provider credential, connector, or external target;
- operation: read, create, update, delete, execute, publish, or transmit;
- scope: exact resource, project, folder, provider, or task;
- conditions: expiry, approval requirement, sensitivity, and allowed destination.

## 3. Tool execution
- Model-generated tool calls are proposals only.
- Tool Gateway validates the tool ID and input schema.
- Permission Manager authorizes the actor/resource/operation/scope.
- Tool Runtime executes only the authorized operation.
- Sensitive writes and externally visible side effects require explicit approval.
- Record a redacted audit event for request, decision, execution result, and failure.

## 4. Context and data boundaries
- Agents receive least-privilege context scoped to the task.
- Model-private memory is not shared with another model/agent by default.
- Librarian source ingestion requires an explicit grant.
- Draft Librarian reports cannot be published as Approved Knowledge without user approval.
- Local private context must not be sent to cloud providers through implicit fallback.

## 5. Denials and failures
Return a structured denial reason without leaking secrets. A denied operation must not be retried through another tool or provider to evade policy. Permission failures are not transient network errors.

## 6. Acceptance criteria
- Default-deny behavior is tested.
- Permission grants are scoped, revocable, and auditable.
- Agents cannot expand their own permissions.
- Tool execution cannot be invoked outside Tool Runtime.
- Destructive and external side effects have approval tests.
