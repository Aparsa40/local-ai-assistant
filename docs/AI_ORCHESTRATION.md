# AI Orchestration and Conversation Processing

**Status:** Target architecture aligned with merged Phase 7 baseline; Conversation Agent implementation is Phase 8 planned work. Phase 9 owns broader multi-agent collaboration beyond the delivered sequential orchestration baseline.

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
- Plan complex work and decompose it into canonical, atomic task IDs from the InterfaceManager task catalog.
- Resolve each task ID to its deterministic primary model-backed agent and explicit ordered fallbacks.
- Fan out every independent task to its selected agent; a model may own multiple task IDs, and overlapping secondary skills must not create duplicate task execution.
- Track dependencies and require an explicit outcome for every planned task; never silently omit an unassigned task.
- Coordinate handoffs and evaluate combined results; request more evidence or report unresolved disagreement.
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
5. Build a bounded plan by decomposing compound goals into canonical task IDs and resolving each through the InterfaceManager task catalog.
6. Check permissions before protected reads or tool actions.
7. Execute through the selected online/offline strategy.
8. Record model/provider/tool metadata, events, and failures.
9. Evaluate completion criteria and continue, hand off, request approval, or stop.
10. Verify that every required task node has a terminal outcome; validate and compose the aggregate result.
11. Return the response and persist the conversation outcome.

## 6. Tool and permission boundary

A model-generated tool call is only a proposal. Permission Manager checks the actor, resource, operation, scope, and policy. Tool Runtime executes only after authorization. Agents cannot grant permissions, expand their own scopes, or bypass user approval.

## 7. Multi-Agent execution

The Phase 7 implementation merged in PR #21 is the current bounded orchestration baseline. Phase 8 must not assume unimplemented task-catalog routing, parallel fan-out or advanced collaboration. Phase 9 owns broader multi-agent expansion.

When multiple agents are used:
- decompose compound goals into atomic task nodes, each with one canonical task ID, scope, dependency set, and acceptance criterion;
- assign every task node to its primary registered model-backed agent, or to an explicit eligible fallback when policy permits;
- allow one model to own several primary task IDs; treat overlapping secondary skills as fallback eligibility unless independent review is explicitly requested;
- pass versioned structured handoff payloads;
- preserve source, operator, model, task-route, and run provenance;
- evaluate evidence rather than stylistic agreement;
- expose unresolved disagreement and missing task outcomes;
- prevent agents from inheriting permissions implicitly.

Phase 9 owns broader multi-agent collaboration, specialized agent teams and richer coordination beyond the sequential Phase 7 baseline.

## 8. Failure and fallback

- A failed cloud provider may trigger another eligible provider or a local model only when user policy permits.
- Local models may be unavailable due to installation, hardware, memory, or resource pressure.
- Fallback must preserve the original task and disclose material capability changes.
- No suitable model means pause, request user input, or report the limitation; never fabricate completion.
- Tool side effects must not be blindly retried.

## 9. Validation boundary

All online/offline candidate responses converge on Response Validator & Composer. Provider adapters normalize transport behavior; they do not validate factual truth. The validator checks structure, completeness, references, policy, and tool outcomes before final composition.

Related: ARCHITECTURE.md, AGENT_RUNTIME.md, INTERFACE_MANAGER.md, PERMISSIONS.md.


## Phase boundary for Conversation Agent

Phase 8 integrates the existing OrchestrationService through its composition root, with bounded goals, child scopes contained by the authorized request scope, correlation IDs and truthful handling of partial/failed runs. It must not call the application's own HTTP endpoints internally, replace the scheduler, or implement Phase 9 features. Context retrieval and cloud egress are separate authorization decisions; private local context must never be sent to a cloud provider without explicit destination authorization.
