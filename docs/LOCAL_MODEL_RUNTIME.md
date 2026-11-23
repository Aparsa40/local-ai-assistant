# Local Model Runtime — Execution Contract

**Status:** Accepted implementation contract (Phase 2 foundation)  
**Branch:** `feat/local-model-runtime-foundation`  
**Scope:** Local model process/runtime lifecycle, beginning with Ollama  
**Last reviewed:** 2026-11-23

## 1. Purpose

The Local Model Runtime is the application-owned execution layer for local inference engines. It manages runtime availability and model lifecycle without coupling conversation logic, agents, or the Interface Manager to Ollama-specific APIs.

Ollama is the first adapter, not the runtime abstraction. A future llama.cpp, LM Studio, or other local engine must be addable through an adapter without changing Runtime Manager callers.

This contract is both the design decision and the acceptance checklist for this implementation.

## 2. Boundaries and ownership

| Component | Owns | Must not own |
|---|---|---|
| Interface Manager | Provider-neutral provider discovery and inference delegation | Local process ownership, model load/unload policy |
| Runtime Manager | Local runtime selection, lifecycle orchestration, concurrency, normalized results | Provider catalog curation, conversation history, agent planning |
| Runtime Adapter | Engine-specific process/API operations | Application policy, database schema, UI |
| Runtime Repository | Durable runtime state and lifecycle events | Runtime decisions or process control |
| Runtime Monitor | Read-only health/resource observations | Starting/stopping processes or changing model state |
| Resource Manager | Admission decisions from configured resource limits and observed capacity | Guessing unavailable RAM/VRAM values |
| Conversation/Agent layers | Request intent and task execution | Calling Ollama endpoints directly |

The existing provider adapter remains responsible for chat streaming and catalog discovery through Interface Manager. Runtime Adapter is a separate control-plane adapter for process/model lifecycle. These two adapter contracts must not be conflated.

## 3. Supported lifecycle

### Runtime lifecycle

`unknown → starting → ready → stopping → stopped`

Failure states: `unavailable`, `not_installed`, `failed`, `starting_timeout`.

### Model lifecycle

`discovered → installed → loading → loaded → unloading → installed`

Failure state: `failed`. A model can be installed without being loaded. Loaded state is an observation from the engine, not an inference-success claim.

### State semantics

- `discovered`: known from a provider/catalog source, but not verified as present in the local runtime.
- `installed`: present in the local engine's installed model inventory.
- `loading` / `unloading`: application-issued transition is in progress.
- `loaded`: engine reports the model as resident/loaded.
- `running`: a request is actively executing, when the adapter can observe it.
- `failed`: the most recent requested lifecycle operation failed; retain the error category and timestamp.
- `unknown`: the adapter cannot make a trustworthy observation.

Do not translate `installed` into `loaded`, or `loaded` into successful inference.

## 4. Runtime Adapter contract

Every adapter exposes:

- `runtime_id` and `capabilities`
- `probe()`: normalized availability result
- `ensure_available(auto_start)`: reuse an existing runtime; start only an explicitly managed local process when permitted
- `list_models()`: installed inventory with exact engine model IDs
- `inspect_model(model_id)`: current lifecycle and metadata observation
- `load_model(model_id, options)`
- `unload_model(model_id)`
- `shutdown_owned_process()`: stop only a process started and owned by this application

Adapters must use bounded network/process timeouts, avoid shell execution, avoid terminating externally owned processes, and return safe normalized errors. Remote endpoints must never trigger local process startup.

## 5. Runtime Manager API

The provider-neutral manager exposes asynchronous operations:

- `ensure_runtime(runtime_id, auto_start=True)`
- `list_models(runtime_id, refresh=True)`
- `inspect_model(runtime_id, model_id)`
- `load_model(runtime_id, model_id, options=None)`
- `unload_model(runtime_id, model_id)`
- `shutdown(runtime_id=None)`

The manager serializes conflicting operations per runtime/model, enforces timeouts and resource admission, persists state transitions/events, and returns stable result envelopes. It does not perform chat inference; inference continues through Interface Manager.

## 6. Normalized result envelope

Successful and failed operations return a dictionary with:

- `ok`: boolean
- `runtime_id`, `model_id`: stable identifiers
- `state`: normalized runtime/model state
- `observed_at`: UTC ISO-8601 timestamp
- `data`: operation-specific non-secret metadata
- `error`: null or `{category, message, retryable}`

Never return credentials, environment values, raw process command lines, or unredacted provider error bodies.

## 7. Persistence

SQLite is the current local persistence target. Runtime state is operational state, separate from model catalog metadata and inference success.

Persist:
- Latest per-runtime status and endpoint scope.
- Latest per-model lifecycle state and observation timestamp.
- Model metadata needed to explain installed/loaded state.
- Append-only lifecycle events for start/probe/load/unload/failure/shutdown.

Do not persist transient stream chunks, credentials, or large engine payloads. Runtime events must be bounded by an explicit retention policy in a later maintenance phase; this first foundation must avoid unbounded duplicate polling events.

Existing `ProviderRuntimeStatus`, `ModelRuntimeStatus`, and catalog tables retain their existing meanings. Runtime lifecycle persistence must not overwrite `ModelRuntimeStatus.availability`, which records inference availability.

## 8. Concurrency, resources, and safety

- One runtime start/stop operation at a time per runtime.
- One lifecycle mutation at a time per model; independent models may be inspected concurrently within adapter limits.
- All engine calls have explicit timeouts.
- Resource telemetry may be unavailable; represent it as `unknown`, never as zero.
- Resource limits are configurable and conservative. Do not automatically unload user models in this foundation.
- Never stop a runtime process that the application did not start.
- Do not auto-download/pull models. Installation is a separate explicit user action.
- Never silently switch from local inference to a cloud provider.
- No destructive action is triggered by a GET endpoint.

## 9. Ollama adapter mapping

The first adapter uses:
- `GET /api/version` for runtime readiness.
- `GET /api/tags` for installed models.
- `GET /api/ps` for loaded models.
- `POST /api/generate` with an empty prompt and bounded `keep_alive` for explicit load/unload control.

The existing safe process-start controller is reused. It may start Ollama only for a loopback HTTP endpoint, only when auto-start is enabled, and only via an executable path with `shell=False`. Remote Ollama endpoints are probed but never spawned locally.

## 10. HTTP/API boundary

Runtime inspection endpoints are read-only GETs. Lifecycle mutations use POST:
- `GET /api/runtime/{runtime_id}/status`
- `GET /api/runtime/{runtime_id}/models`
- `GET /api/runtime/{runtime_id}/models/{model_id}`
- `POST /api/runtime/{runtime_id}/models/{model_id}/load`
- `POST /api/runtime/{runtime_id}/models/{model_id}/unload`

Responses expose normalized envelopes only. Model IDs must be treated as path data and safely URL-encoded by clients.

## 11. Failure handling

Expected categories include:
`runtime_not_registered`, `runtime_unavailable`, `runtime_not_installed`, `model_not_installed`, `model_not_found`, `load_failed`, `unload_failed`, `operation_timeout`, `resource_limit_exceeded`, `adapter_error`.

Failures must not erase last-known-good catalog records. A failed load/unload records a failed lifecycle event and preserves the last trustworthy observed state separately from the operation result.

## 12. Delivery sequence

1. Add this contract and keep the roadmap status accurate.
2. Define adapter/result/context interfaces and Runtime Manager.
3. Implement Ollama adapter using the existing process controller.
4. Add runtime state/event persistence without changing inference status semantics.
5. Add read-only status/list/inspect APIs and POST load/unload APIs.
6. Add deterministic unit tests for adapter calls, ownership, timeouts, lifecycle, persistence, and API method safety.
7. Run the full test suite and CI; perform Windows Ollama smoke tests before declaring the phase complete.

## 13. Acceptance criteria

- Runtime Manager contains no Ollama endpoint or process-specific logic.
- Ollama is registered through the Runtime Adapter contract.
- Existing Ollama auto-start behavior remains backward compatible.
- Existing Interface Manager chat/catalog behavior is unchanged.
- Installed and loaded model states are distinct and accurately sourced.
- Only application-owned processes can be shut down by the application.
- Load/unload are explicit POST operations; GET operations are read-only.
- Runtime lifecycle state/events persist independently from inference status.
- All new failure paths are bounded, normalized, and tested.
- Existing tests remain green; no tests are removed, skipped, or weakened.

## 14. Non-goals for this increment

- Automatic model download/pull.
- Automatic model selection or routing.
- Automatic unload/eviction based on RAM/VRAM.
- Cloud-provider lifecycle management.
- Agent Runtime, Supervisor, or Multi-Agent execution.
- Encrypted credential vault or PostgreSQL migration.
- Full GPU telemetry where the engine/OS does not expose a reliable source.

These are deliberately deferred. This increment establishes a safe, testable runtime control plane first.
