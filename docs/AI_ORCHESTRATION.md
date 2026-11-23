# AI Orchestration and Conversation Processing

**Status:** Accepted target design; current chat orchestration remains manual-provider oriented.

## 1. Purpose and boundaries

Conversation Processing owns the user-facing conversation lifecycle: receiving a request, loading authorized context, recording conversation events, delegating goal-oriented work, and returning a validated response.

Agent Runtime owns the lifecycle and execution loop of goal-oriented agents. It hosts the Conversation Agent and any specialized agents. The Supervisor is a specialized coordinating agent hosted by Agent Runtime; it is not the Runtime itself.

Online and offline inference are execution strategies available to agents through Interface Manager. They are not separate chat products.

## 2. Responsibilities

### Conversation Processing
- Receive and normalize user requests.
- Resolve conversation history and authorized context.
- Determine whether the request is a direct response, deterministic workflow, or agent task.
- Create and track a conversation-level task.
- Delegate goal-oriented work to Agent Runtime.
- Record messages, task events, and execution provenance.
- Pass candidate output to Response Validator & Composer.

### Agent Runtime
- Host and manage agent definitions and runs.
- Enforce lifecycle, state, iteration, cancellation, and handoff rules.
- Provide agents with scoped context and access to approved tools.
- Route model calls through online/offline execution paths and Interface Manager.
- Evaluate task completion against explicit criteria.

### Supervisor Agent
- Plan complex work and decompose it into tasks.
- Select eligible agent roles and model capabilities.
- Coordinate handoffs and evaluate combined results.
- Request more evidence or report unresolved disagreement.
- Never grant permissions or directly execute tools.

## 3. Deterministic baseline

The system must not depend on an LLM for every control decision.

Deterministic application logic should handle:
- request/run IDs and lifecycle transitions;
- simple intent/rule matching;
- provider/model availability checks;
- permission checks and policy enforcement;
- fixed workflows and bounded retries;
- local retrieval and deterministic extraction;
- iteration limits, cancellation, and failure states.

When no LLM is available, the application may still search, retrieve, extract, and run fixed workflows. It must not claim to provide general language reasoning without a language model.

## 4. Online and offline execution

Both paths must satisfy the same provider-neutral execution contract:

- **Online:** Agent Runtime -> Online Execution Strategy -> Interface Manager -> eligible cloud provider adapter.
- **Offline:** Agent Runtime -> Offline Execution Strategy -> Interface Manager -> local provider adapter (for example, Ollama).

Routing considers task capability, context/output limits, modalities, tool support, credentials, health, quota state, latency/cost preferences, and user policy.

Internet connectivity alone does not determine the execution path. A cloud-to-local switch must preserve the task checkpoint and authorized context, but must re-check the local model's capabilities and context window. It must never silently send private local data to a cloud provider.

If no suitable local model is available, pause or fail the affected task clearly. Deterministic workflows may continue when they do not require language reasoning.

## 5. Agent execution lifecycle

1. Receive a request and create a traceable conversation/task ID.
2. Classify the request and determine required data, tools, and capabilities.
3. Resolve authorized context.
4. Select a direct-response path or create an agent run.
5. Build a bounded plan (deterministic first; Supervisor assistance when useful).
6. Check permissions before protected reads or tool actions.
7. Execute through the selected online/offline strategy.
8. Record model/provider/tool metadata, events, and failures.
9. Evaluate completion criteria and continue, hand off, request approval, or stop.
10. Validate and compose the candidate result.
11. Return the response and persist the conversation outcome.

## 6. Tool and permission boundary

A model-generated tool call is only a proposal. Permission Manager checks the actor, resource, operation, scope, and policy. Tool Runtime executes only after authorization. Agents cannot grant permissions, expand their own scopes, or bypass user approval.

## 7. Multi-Agent execution

Multi-Agent execution is optional and task-driven. It is not enabled merely because multiple models are configured.

When multiple agents are used:
- assign distinct responsibilities and acceptance criteria;
- pass versioned structured handoff payloads;
- preserve source and model provenance;
- evaluate evidence rather than stylistic agreement;
- expose unresolved disagreement;
- prevent agents from inheriting permissions implicitly.

Start with one bounded agent. Add a Supervisor and specialized agents only after lifecycle, state persistence, permission enforcement, cancellation, and evaluation are reliable.

## 8. Failure and fallback

- A failed cloud provider may trigger another eligible provider or a local model only when user policy permits.
- Local models may be unavailable due to installation, hardware, memory, or resource pressure.
- Fallback must preserve the original task and disclose material capability changes.
- No suitable model means pause, request user input, or report the limitation; never fabricate completion.
- Tool side effects must not be blindly retried.

## 9. Validation boundary

All online/offline candidate responses converge on Response Validator & Composer. Provider adapters normalize transport behavior; they do not validate factual truth. The validator checks structure, completeness, references, policy, and tool outcomes before final composition.

Related: ARCHITECTURE.md, AGENT_RUNTIME.md, INTERFACE_MANAGER.md, PERMISSIONS.md.
