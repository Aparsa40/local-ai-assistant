# Local Model Runtime — Execution Contract

**Status:** Accepted implementation contract; Phase 1 implementation starts on `feat/local-model-runtime`.
**Owner:** Local Model Runtime
**Depends on:** Interface Manager foundation, Provider adapters, existing SQLite catalog/runtime tables.
**First adapter:** Ollama.
**Non-goal:** Replacing Interface Manager or introducing Agent Runtime in this phase.

## 1. Purpose and boundary

Local Model Runtime is the control plane for execution engines running on the user's machine. It owns runtime lifecycle and execution observations; it does not own provider discovery policy, model suitability analysis, conversation orchestration, agent planning, or tool permissions.

The architecture has three distinct responsibilities:

- **Interface Manager:** provider-neutral access to provider capabilities, model discovery, quota and inference interfaces.
- **Local Model Runtime:** lifecycle and execution management for local runtime engines and their loaded models.
- **Provider/Runtime adapters:** translate the common runtime contract to a concrete engine API (initially Ollama).

A provider is not necessarily a runtime. Cloud providers remain behind Interface Manager and are not forced into local process lifecycle abstractions.

## 2. Architectural invariants

1. Runtime Manager is engine-neutral; it must not import Ollama-specific modules.
2. Runtime adapters are the only layer allowed to know engine-specific endpoints, process commands, or response formats.
3. Runtime state is evidence-based. Unknown is a valid state and must never be silently converted to stopped, unloaded, or healthy.
4. The application may stop only processes it started and still owns. It must never terminate a user-managed or externally managed runtime.
5. Process startup is permitted only for explicitly configured loopback HTTP endpoints. Remote endpoints are probe-only.
6. No destructive model operation (pull, delete, unload, process termination) is implicit in discovery or inference.
7. Runtime lifecycle calls are bounded by timeouts and cancellation; no unbounded polling or background task is created implicitly.
8. Model identity is the pair `(runtime_id, model_id)`; provider identity and model display names are not substitutes.
9. Runtime telemetry and model capability evidence are separate data. A loaded model is not necessarily suitable for chat.
10. Persisted state is an observation/history aid, not proof of current live state after restart.
11. Existing provider APIs and current manual provider/model selection remain backward compatible during this phase.
12. Runtime failures are represented by stable categories and safe messages; raw secrets, environment variables, or credential values never enter logs or API responses.

## 3. Runtime domain model

### 3.1 Runtime identity

A runtime descriptor contains:

- `runtime_id`: stable adapter key, initially `ollama`.
- `display_name`: human-readable engine name.
- `endpoint`: configured base URL; secrets/userinfo are forbidden.
- `scope`: `local` or `remote`.
- `capabilities`: supported operations such as `list_models`, `list_loaded_models`, `load_model`, `unload_model`, `chat`.
- `auto_start`: whether the application may start the local engine, subject to loopback restrictions.

### 3.2 Model identity and observation

A model observation contains:

- `runtime_id`, `model_id`
- `installed`: `true | false | null`
- `loaded`: `true | false | null`
- `state`: `discovered | installed | loading | loaded | running | unloading | unloaded | failed | unknown`
- `observed_at`: UTC timestamp
- `source`: adapter/API/process evidence source
- optional engine metadata (digest, size, quantization, context length)

`null` means unknown/unavailable evidence. Do not infer loaded state from an installed catalog entry or a previous successful inference.

### 3.3 Lifecycle states

Runtime lifecycle:
`unknown -> checking -> ready | starting -> ready | unavailable | not_installed | failed`.

Model lifecycle:
`unknown -> discovered -> installed -> loading -> loaded -> running -> unloading -> installed`.
A runtime may report a direct transition (for example, installed to loaded) when the adapter does not expose intermediate events. Any transition to `failed` retains a categorized error and the last known observation.

The implementation must validate transitions centrally. Adapter responses are normalized before state is changed.

## 4. Core components and ownership

### 4.1 RuntimeManager

Public orchestration facade. Responsibilities:

- register and resolve runtime adapters;
- expose runtime status and model observations;
- ensure a runtime is reachable (or start it only under the safety rules);
- list installed and loaded models independently;
- request model load/unload only when the adapter supports it;
- delegate inference to the selected runtime adapter when explicitly requested;
- normalize errors, enforce timeouts, and publish observations.

It must not contain engine-specific HTTP paths or shell commands.

### 4.2 RuntimeAdapter contract

Async adapter interface:

- `probe() -> RuntimeProbe`
- `ensure_ready(auto_start: bool) -> RuntimeProbe`
- `list_installed_models() -> list[ModelObservation]`
- `list_loaded_models() -> list[ModelObservation] | None`
- `load_model(model_id, options) -> ModelObservation` (optional capability)
- `unload_model(model_id) -> ModelObservation` (optional capability)
- `stream_chat(model_id, messages, options) -> async iterator[str]` (optional capability)
- `close() -> None` (release adapter-owned resources; must not kill externally owned processes)

Unsupported operations raise a typed `RuntimeCapabilityError`, not a generic success or fabricated state.

### 4.3 OllamaRuntimeAdapter

Initial adapter responsibilities:

- reuse the configured Ollama endpoint when healthy;
- start `ollama serve` only for an unreachable loopback HTTP endpoint when auto-start is enabled;
- use `/api/version` for readiness, `/api/tags` for installed models and `/api/ps` for loaded models;
- keep installed-model discovery successful when loaded-state telemetry fails;
- use `/api/generate` or `/api/chat` only through the existing, tested provider inference path until a deliberate runtime-inference migration is approved;
- never stop a process it did not create;
- retain proxy behavior for remote endpoints and bypass environment proxies only for local loopback calls.

The existing `LocalRuntimeController` is the migration source for safe process startup. It must be moved behind the adapter boundary without duplicating process ownership logic.

### 4.4 RuntimeRegistry

In-memory current-session registry keyed by `runtime_id` and `(runtime_id, model_id)`. It stores normalized latest observations and timestamps. It is not a replacement for durable catalog/history storage.

### 4.5 RuntimeMonitor

Phase 1 uses explicit, bounded probes requested by callers. No always-on polling loop or scheduler is introduced. Periodic monitoring can be added later with explicit lifecycle, shutdown, and resource policy.

### 4.6 ResourceManager

Phase 1 exposes resource telemetry only when the adapter/host can provide reliable evidence. It must not guess VRAM/RAM usage or impose automatic eviction. Concurrency limits are enforced conservatively at the manager boundary and can be configured; no automatic unload policy is introduced.

### 4.7 ExecutionContext

An immutable request-scoped value containing runtime/model identity, timeout, cancellation signal, normalized generation options, and correlation ID. It must not contain API secrets. The initial slice may define the type before all call sites migrate.

### 4.8 RuntimeEvents

Normalized in-process events: `runtime.checking`, `runtime.ready`, `runtime.unavailable`, `runtime.started`, `model.discovered`, `model.loaded`, `model.unloaded`, `inference.started`, `inference.completed`, `inference.failed`. Event delivery is optional/no-op by default in Phase 1; no external event bus is required.

## 5. Error contract

Stable categories include:

- `runtime_not_registered`
- `runtime_unreachable`
- `runtime_start_disabled`
- `runtime_not_installed`
- `runtime_start_failed`
- `runtime_start_timeout`
- `runtime_process_exited`
- `runtime_operation_unsupported`
- `model_not_installed`
- `model_load_failed`
- `model_unload_failed`
- `runtime_request_timeout`
- `runtime_cancelled`
- `runtime_protocol_error`

Errors include a safe human-readable message, runtime/model identity when known, retryability where determinable, and the original exception only as an internal cause. Never include credentials or full environment data.

## 6. Persistence contract

Reuse the existing SQLite foundation; do not create a second database or duplicate catalog tables.

- `provider_runtime_status`: latest provider/runtime reachability observation; use existing `runtime_details` for normalized runtime information where appropriate.
- `model_runtime_status`: latest observed model availability and last inference outcome.
- `live_model_catalog`: installed/discovered catalog facts, not loaded-state truth.
- `catalog_sync_history`: catalog synchronization history only, not every runtime probe.
- `provider_intelligence_reports`: intelligence reports remain owned by Provider Intelligence.

Phase 1 persists normalized runtime and model observations through a repository/service boundary. If schema changes become necessary, add an explicit migration and regression tests; do not rely on `create_all` to alter existing columns.

Persisted observations must include source and timestamp. On application restart, the manager must re-probe before presenting a persisted observation as current.

## 7. Configuration and security

Runtime configuration is read from the existing provider settings and normalized into a runtime descriptor. Existing `providers.ollama.base_url` and `auto_start` remain compatible.

- Accept only valid HTTP(S) URLs without embedded username/password.
- Auto-start is restricted to HTTP loopback endpoints.
- Remote runtime endpoints may be probed but never process-started or process-stopped by this application.
- Use argument arrays with `shell=False`; never interpolate commands through a shell.
- Apply bounded connect/read/startup timeouts.
- Do not expose process command lines, environment variables, or secrets to the browser.
- No new credential storage mechanism is introduced in this phase.

## 8. Public Python API (Phase 1 target)

The stable internal entry point is:

```python
manager = RuntimeManager(adapters={...})
status = await manager.ensure_ready("ollama", auto_start=True)
installed = await manager.list_installed_models("ollama")
loaded = await manager.list_loaded_models("ollama")
```

The concrete signatures may use typed dataclasses, but callers must not depend on Ollama response JSON.

Initial package layout:

```text
core/runtime/
  __init__.py
  contracts.py
  errors.py
  registry.py
  runtime_manager.py
  adapters/
    __init__.py
    ollama.py
```

Additional monitor/resource/event services are introduced only when their behavior is implemented and tested; empty placeholder modules are not acceptable.

## 9. Delivery slices

### Slice A — Contract and adapter foundation

- this document;
- typed contracts, lifecycle enums, observations, and typed errors;
- adapter protocol and runtime registry;
- Ollama adapter wrapping the existing safe local process controller and API observations;
- RuntimeManager for readiness and installed/loaded model queries;
- unit tests with mocked HTTP/process boundaries.

### Slice B — Persistence and application integration

- repository methods for runtime/model observations;
- explicit tests for latest-state persistence and unknown-state preservation;
- integrate runtime readiness into the existing explicit Ollama connection flow without changing cloud-provider behavior;
- avoid duplicate probes where a single result can be reused.

### Slice C — Model lifecycle and inference boundary

- implement load/unload only if the engine exposes reliable operations and the user explicitly requests them;
- define bounded execution context, cancellation, and concurrency behavior;
- migrate inference only after parity tests prove existing Ollama streaming behavior is preserved.

### Slice D — Operational hardening

- diagnostics, shutdown behavior, Windows/Linux/macOS process tests where available;
- failure, timeout, cancellation, proxy, and offline tests;
- documentation and CI verification.

## 10. Acceptance criteria

Slice A is complete when:

1. RuntimeManager has no Ollama-specific imports.
2. OllamaRuntimeAdapter is the only runtime layer that knows Ollama endpoints/process startup.
3. Existing Ollama process is reused; application starts only a missing local server when explicitly allowed.
4. Remote endpoints are probe-only and never trigger local process startup.
5. Installed and loaded model states are independently reported; loaded telemetry failure yields unknown, not false.
6. Adapter errors map to stable typed categories and do not leak secrets.
7. RuntimeManager can be tested without a real Ollama installation or network.
8. Existing provider discovery, settings, and chat streaming tests remain green.
9. No agent, supervisor, tool execution, automatic model download, model deletion, or automatic unload behavior is introduced.
10. The contract and implementation status in the docs index/roadmap match shipped code.

Slice B-D acceptance criteria are tracked separately and must not be marked complete merely because Slice A passes.
