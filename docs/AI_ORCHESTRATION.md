# AI Orchestration and Conversation Processing

**Status:** Accepted target design; current orchestration remains simpler and manual-provider oriented.

## 1. Purpose

Conversation Processing is the single module responsible for the lifecycle of a user request. It coordinates analysis, planning, execution, context access, recording, and response validation.

Online and offline execution are two engines within this module, not separate chat products.

## 2. Internal components

- Request Analyzer: classify intent, constraints, expected output, and data requirements.
- Task Planner: decompose complex requests into tasks and dependencies.
- Execution Router: choose an eligible execution path and model based on task requirements and actual availability.
- Online Execution Engine: invoke cloud providers through Interface Manager.
- Offline Execution Engine: invoke local models and permitted local knowledge.
- Context & Memory Manager: assemble only authorized conversation, model memory, and approved knowledge.
- Conversation Recorder: persist messages, task events, model/provider metadata, tool calls, and outcomes.
- AI Supervisor: optional LLM-assisted planner for complex decomposition and coordination.

## 3. Deterministic baseline

The system must not depend on an LLM to perform every routing or control decision.

A deterministic dispatcher should handle:
- simple intent/rule matching;
- provider/model availability checks;
- permission checks;
- fixed workflows;
- bounded retries and fallback;
- local retrieval and deterministic extraction;
- routing to an LLM only when the task requires it.

When no LLM is available, the application may still search, retrieve, extract, and present known information. It must not claim to provide general language reasoning without a language model.

## 4. AI Supervisor

The Supervisor may use one or more models to:
- plan complex work;
- decompose tasks;
- select models based on capability metadata;
- propose tools and connectors;
- compare or reconcile model outputs;
- request additional evidence.

The Supervisor is not a security authority. It cannot grant permissions, directly execute tools, or override user policies. Its plan is subject to deterministic validation and permission checks.

## 5. Routing criteria

Routing may consider:
- task type and required capability;
- context/output limits;
- required modalities;
- tool support;
- configured credentials;
- provider health and availability;
- quota/rate-limit state;
- latency/cost preferences;
- user-selected provider/model constraints;
- local/offline requirements.

Unknown values must remain unknown and should not be scored as confirmed availability.

## 6. Execution lifecycle

1. Receive a user request and create a traceable request ID.
2. Analyze task requirements and identify data/tool needs.
3. Resolve permitted context through Context & Memory Manager.
4. Plan tasks; use deterministic planning for simple workflows and optional Supervisor assistance for complex ones.
5. Check permissions before any protected data access or tool execution.
6. Select online/offline engine based on capability and availability.
7. Execute tasks and collect normalized results.
8. Record model/provider/tool metadata and failures.
9. Send candidate output to Response Validator & Composer.
10. Return the validated response to the UI and persist the conversation event.

## 7. Multi-model work

Multi-model execution is optional and task-driven, not a default requirement for every message. When used:
- assign distinct tasks or independent review roles;
- preserve each model's output and provenance;
- compare evidence, not merely stylistic agreement;
- expose unresolved disagreement;
- do not treat majority vote as proof of truth.

## 8. Failure and fallback

- A failed cloud provider may trigger another eligible provider or local model, subject to user policy.
- A local model may be unavailable due to missing installation, hardware limits, or resource pressure.
- Fallback must preserve the original request and explain material changes in capability.
- Never silently send private local data to a cloud provider as a fallback.
- If no suitable model exists, offer deterministic operations where possible and explain the limitation.

## 9. Validation boundary

All online/offline candidate responses converge on Response Validator & Composer. Provider adapters normalize transport responses; they do not validate factual truth. The Validator checks structure, completeness, references, policy, and tool outcomes before final composition.

Related: [ARCHITECTURE.md](ARCHITECTURE.md), [INTERFACE_MANAGER.md](INTERFACE_MANAGER.md), [PERMISSIONS.md](PERMISSIONS.md).
