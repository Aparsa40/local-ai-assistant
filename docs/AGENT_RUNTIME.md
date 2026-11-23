# Agent Runtime

**Status:** Accepted target architecture; not implemented yet.

## 1. Purpose

Agent Runtime is the application-owned execution environment for goal-oriented agents. It manages agent registration, task execution, lifecycle, state, handoffs, and feedback loops.

It is not an LLM, a provider, or a model router. An agent may use an online LLM, a local LLM, deterministic application logic, or a hybrid of these.

## 2. Core distinction

- **LLM:** a reasoning and generation engine that receives input and returns output.
- **Agent:** a goal-oriented execution unit with a defined responsibility, state, permitted capabilities, and a controlled execution loop.
- **Agent Runtime:** the infrastructure that hosts and controls agents.
- **Supervisor Agent:** a specialized agent that plans and coordinates work across tasks or other agents.
- **Multi-Agent System:** multiple agents with explicit responsibilities and controlled communication/handoffs.

A module is not automatically an agent. It qualifies as an agent when it owns a goal-oriented workflow and can manage its execution state and completion criteria. Ordinary infrastructure services remain services.

## 3. Runtime responsibilities

- Agent Registry: register agent types, versions, contracts, and enabled state.
- Lifecycle Manager: create, start, pause, resume, cancel, and finish agent runs.
- Task Manager: represent goals, subtasks, dependencies, deadlines, and completion criteria.
- State Manager: persist run state and checkpoints so eligible work can resume.
- Context Builder: provide only the context authorized and needed for the task.
- Execution Controller: run bounded plan/act/observe/evaluate cycles.
- Tool Access Gateway: expose tools through the permission and execution boundary.
- Handoff Manager: pass structured task results between agents.
- Run Evaluator: determine whether acceptance criteria are met, more work is needed, or the run must stop.
- Audit/Event Recorder: retain decisions, tool activity, model/provider identity, failures, and outcomes.

## 4. Agent contract

Each agent definition should specify:

| Field | Meaning |
| --- | --- |
| agent_id | Stable identifier |
| version | Version of the agent workflow/contract |
| goal | Responsibility and intended outcome |
| input_schema | Required task input |
| output_schema | Expected structured result |
| completion_criteria | Conditions for success |
| allowed_models | Model roles or capability requirements, not hard-coded vendor names |
| allowed_tools | Tool IDs that may be requested |
| data_scopes | Explicitly permitted context and knowledge scopes |
| max_iterations | Bounded execution limit |
| approval_policy | Actions requiring user confirmation |

An agent definition describes what the agent is allowed and expected to do. It does not itself grant permissions.

## 5. Execution lifecycle

1. Receive a task with a stable run ID.
2. Validate the agent definition and input schema.
3. Resolve task context through permission-aware services.
4. Select an execution strategy and eligible model, if language reasoning is required.
5. Produce or update a bounded plan.
6. Request an action or tool call.
7. Validate the proposed action and check permissions in application code.
8. Execute only authorized actions.
9. Observe the result and update run state.
10. Evaluate completion criteria.
11. Continue, hand off, request user input/approval, or stop.
12. Persist the final result and audit trail.

The model proposes reasoning and actions. Runtime code enforces schemas, iteration limits, permissions, execution, state transitions, and stop conditions.

## 6. Online and offline execution

Agent Runtime must not depend on a cloud provider.

- Online inference is accessed through Interface Manager and eligible cloud-provider adapters.
- Offline inference is accessed through Interface Manager and local-provider adapters such as Ollama.
- Deterministic agents may run without any LLM.
- The same agent contract should work with different eligible models where capability requirements are met.
- Switching engines must preserve the task input, authorized context, and checkpoint state. It must not assume two models have identical capabilities or context windows.
- A cloud-to-local fallback must never send private local data to a cloud provider.
- If no eligible local model is available, the run must pause or report the limitation rather than claim success.

## 7. Security boundaries

- Agent definitions are not permission grants.
- Model-generated tool calls are proposals, not authorization.
- Every protected read or write is checked by the Permission Manager.
- Tool execution occurs only through Tool Runtime.
- Agents receive least-privilege, task-scoped context.
- Secrets are never placed in prompts or ordinary task logs.
- External content and model output are untrusted until validated.
- Destructive or externally visible actions require explicit approval according to policy.

## 8. Supervisor and Multi-Agent boundary

The Supervisor is an agent hosted by Agent Runtime; it is not the Runtime itself.

Initially, one agent should complete a bounded workflow end to end. Multi-Agent orchestration is introduced only after single-agent execution, state persistence, permission enforcement, cancellation, and evaluation are reliable.

For multi-agent runs:
- each agent receives a scoped task and explicit acceptance criteria;
- handoffs use versioned structured outputs;
- shared state is mediated by runtime services;
- agents cannot silently expand one another's permissions;
- disagreement and incomplete results remain visible;
- the Supervisor coordinates but does not bypass validation or security boundaries.

## 9. Initial implementation sequence

1. Define agent/task/run contracts and deterministic lifecycle management.
2. Add a single bounded agent with no autonomous external side effects.
3. Add model-backed planning and tool proposals through Interface Manager.
4. Add permissioned Tool Runtime and resumable checkpoints.
5. Add a Supervisor and a second specialized agent.
6. Add multi-agent handoffs and coordination.

## 10. Non-goals for the first version

- No unrestricted autonomous computer control.
- No self-granting permissions.
- No unbounded recursive planning or tool loops.
- No mandatory cloud model.
- No assumption that every application module must become an agent.
- No multi-agent complexity before a single-agent workflow is testable.

Related: AI_ORCHESTRATION.md, INTERFACE_MANAGER.md, PERMISSIONS.md, ARCHITECTURE.md.
