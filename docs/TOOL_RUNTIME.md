# Tool Runtime

**Project:** Local AI Assistant  
**Phase:** 5 of 11 — Tool Runtime & Permission Manager  
**Status:** Tool Registry and Tool Runtime implemented and CI-validated; existing domain/API integration remains pending WP-5.6.

## 1. Security boundary

A model-generated tool call is an untrusted proposal, not an authorization. Only application code may register a tool handler. Tool definitions do not grant access. Every invocation must eventually pass through Tool Runtime, which validates the request, asks PermissionManager for an exact-scope decision, consumes a required approval, executes within limits, normalizes the result, and records audit events.

No shell, arbitrary Python, unrestricted filesystem, browser/computer-control, or unrestricted network handlers are registered by this phase baseline.

## 2. Implemented registry contracts

- `ToolDefinition`: stable tool ID, semantic version, JSON input/output schemas, resource type, operation, risk class, timeout, input/output byte limits, approval requirement, and enabled state.
- `ToolCallRequest`: tool ID/version, typed AccessRequest, JSON input object, and optional approval ID.
- `ToolRiskClass`: `read_only`, `mutating`, `destructive`, and `external_side_effect`.
- `ToolRegistry`: explicit registration, duplicate rejection, enabled-state check, request validation, and a public metadata catalog.

A handler is registered by trusted application code and stored separately from its public tool metadata. The public catalog does not expose handlers or raw schema internals.

## 3. Input schema policy

The registry supports a deliberately restricted JSON Schema subset:

- Types: object, array, string, integer, number, boolean, null.
- Object: properties, required, and explicit additionalProperties behavior.
- Array: item schema and minimum/maximum item count.
- String: minimum/maximum length.
- Number/integer: minimum/maximum values.
- Enum: bounded allowed values.

Unsupported keywords (including remote/local references and arbitrary schema extensions) are rejected. Nested schema depth, property count, schema size, input size, and tool execution bounds are limited. Unknown object properties are rejected by default.

## 4. Risk and approval rules

- Read-only tools must declare the read operation.
- Mutating tools are limited to create/update operations.
- Destructive tools must declare delete and require explicit approval.
- External side-effect tools must declare publish/transmit and require explicit approval.
- Tool definitions cannot disable the central permission decision or issue grants.

## 5. Implemented runtime sequence

1. Resolve exact tool ID and version from the trusted registry.
2. Validate the typed AccessRequest and complete input schema.
3. Verify resource type and operation match the registered definition.
4. Evaluate PermissionManager; deny on any missing, invalid, expired, revoked, or unsupported grant.
5. If required, consume the one-time approval bound to the same request and canonical action hash.
6. Invoke the registered handler within its timeout and input/output limits.
7. Validate/normalize the result; do not expose raw exceptions or credentials.
8. Persist correlated redacted audit events.

The runtime does not retry a denied action through another tool. If required audit persistence fails before a side effect, execution stops. Permission is rechecked immediately before handler invocation to reduce revocation races. Cancellation and timeout behavior do not falsely report success. If an operation may have caused a side effect but its final audit event cannot be persisted, the result explicitly reports that the side effect may have occurred.

## 6. Current limitations

- Tool Registry and Tool Runtime exist, but no production tool handlers are registered by this work package.
- Existing user-facing conversation, memory, provider, runtime, and configuration APIs use `PermissionManager` with `LocalApplicationPolicy` and `require_access`; they are not invoked as model-generated tools and therefore do not route through ToolRuntime.
- MemoryService uses an explicit adapter when configured; it remains default-deny without one. ContextManager is used for bounded conversation history in chat, and memory scopes are not attached implicitly.
- Tool schemas and registration are not a sandbox. Handler code remains trusted application code and must use narrow injected capabilities.
- No general-purpose shell, arbitrary code execution, unrestricted file access, or external connector is provided.
- Hosted authentication and a credential vault are not implemented.
