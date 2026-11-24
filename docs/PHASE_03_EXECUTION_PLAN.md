# Phase 3 — Local Model Runtime

**Project:** Local AI Assistant  
**Phase:** 3 of 11  
**Document type:** Authoritative execution plan  
**Status:** Software implementation completed; hardware-dependent live load validation deferred  
**Branch delivered:** `feat/local-model-runtime-foundation`  
**Merge commit:** `d30621e85f7f58096f57cf0e40f7dace23a60b21`  
**Pull request:** [#7](https://github.com/Aparsa40/local-ai-assistant/pull/7)  
**Related duplicate PR:** [#8](https://github.com/Aparsa40/local-ai-assistant/pull/8) — closed without merge  
**Last reviewed:** 2026-11-24

## 1. Purpose

Provide a provider-neutral control plane for local inference-engine availability and model lifecycle. The application must be able to inspect a local runtime and perform explicit model load/unload operations without coupling Interface Manager, conversation workflows, or future agents to Ollama-specific process and HTTP details.

Ollama is the first Runtime Adapter, not the runtime abstraction itself.

## 2. Scope

### In scope

1. Define Runtime Adapter, Runtime Manager, result, and lifecycle contracts.
2. Implement the Runtime Manager orchestration boundary.
3. Implement Ollama as the first Runtime Adapter.
4. Distinguish runtime readiness, model installation, model loaded state, and inference availability.
5. Provide read-only runtime status, snapshot, inventory, and inspection.
6. Provide explicit bounded load/unload operations.
7. Enforce process ownership: stop only processes started by this application.
8. Persist runtime status, model lifecycle observations, and lifecycle events separately from provider catalog and inference status.
9. Normalize errors, bound timeouts/concurrency, and enforce conservative resource admission.
10. Test lifecycle behavior and document hardware-dependent validation limitations.

### Out of scope

- Model downloads/pulls.
- Automatic model selection, task routing, or cloud fallback.
- Automatic model eviction.
- GPU telemetry guarantees.
- Additional local engines beyond the first adapter.
- Agent Runtime, Supervisor, and Multi-Agent execution.
- Encrypted credential vault or PostgreSQL deployment.

## 3. Execution steps

### Step 3.1 — Audit current local runtime behavior

- Inspect existing Ollama startup/reuse behavior.
- Identify process ownership and endpoint scope.
- Preserve compatibility with Interface Manager and existing Ollama chat/catalog integration.
- Do not merge provider catalog discovery with local runtime lifecycle control.

**Deliverable:** local runtime compatibility and ownership baseline.

### Step 3.2 — Define provider-neutral runtime contracts

Define:
- Runtime Adapter identity and capabilities;
- runtime availability and model lifecycle operations;
- normalized result envelope;
- safe error categories;
- timeout and concurrency policies;
- process ownership rules.

Required adapter operations include availability checks, installed inventory, model inspection, load, unload, and owned-process shutdown.

**Deliverable:** adapter and manager contracts.

### Step 3.3 — Implement Runtime Manager

- Register runtime adapters by stable runtime ID.
- Orchestrate ensure/read/inspect/load/unload/shutdown operations.
- Serialize conflicting runtime/model lifecycle mutations.
- Apply bounded timeouts and concurrency limits.
- Apply conservative resource admission without guessing missing RAM/VRAM telemetry.
- Persist operation results through a repository.
- Keep Runtime Manager free of Ollama-specific endpoint/process logic.

**Deliverable:** provider-neutral runtime orchestration.

### Step 3.4 — Implement Ollama Runtime Adapter

- Reuse an already-running local Ollama server when available.
- Start Ollama only when auto-start is explicitly enabled and endpoint scope is loopback HTTP.
- Never spawn a local process for a remote endpoint.
- Use bounded HTTP/process operations.
- Use installed inventory and loaded-model inspection as separate observations.
- Verify the resulting lifecycle state after load/unload.
- Stop only the process started and owned by this application.

**Deliverable:** first operational runtime adapter.

### Step 3.5 — Add runtime persistence

Persist:
- latest runtime status and endpoint scope;
- latest per-model lifecycle state and observation timestamp;
- safe model metadata needed to explain the state;
- lifecycle events for meaningful operations and failures.

Keep these records separate from:
- provider catalog metadata;
- provider connection/catalog reachability;
- model inference availability and last successful inference.

Polling and read-only inspection must not create an unbounded duplicate event log. A failed lifecycle operation must not erase the last trustworthy observed model state.

**Deliverable:** Runtime Repository and SQLite lifecycle records.

### Step 3.6 — Expose safe API operations

Read-only GET operations:
- runtime status;
- combined runtime health/inventory snapshot;
- installed model inventory;
- per-model inspection.

Explicit POST operations:
- model load;
- model unload;
- shutdown of an application-owned runtime process only.

No destructive lifecycle operation may be triggered by GET.

**Deliverable:** normalized runtime API boundary.

### Step 3.7 — Test and validate

Required deterministic coverage:
- adapter contract and registry;
- runtime readiness and inventory;
- installed versus loaded semantics;
- load/unload success and failure verification;
- process ownership and remote endpoint restrictions;
- timeouts, concurrency, resource admission;
- persistence and event recording;
- API method safety and normalized errors;
- regression behavior for Interface Manager and chat.

Run:
- `python -m compileall -q core main.py`
- `python -m pytest -q`
- `node --check static/app.js`

Live hardware validation must be reported separately from deterministic software tests. Never pressure a resource-constrained machine to force a model-load success.

**Deliverable:** passing software checks and an honest environment validation report.

### Step 3.8 — Document and deliver

- Update Local Model Runtime contract, architecture snapshot, roadmap, README, and PR notes.
- Report exact test/check results.
- Record unverified hardware-dependent behavior as unverified.
- Merge only after required checks pass and explicit authorization.

**Deliverable:** merged runtime foundation and traceable validation record.

## 4. Main implementation map

| Area | Repository location |
|---|---|
| Runtime Manager and contracts | `core/runtime/` |
| Ollama Runtime Adapter | `core/runtime/adapters/` |
| Runtime persistence adapter | `core/runtime/repository.py` |
| Runtime SQLAlchemy records | `core/database.py` |
| Runtime API boundary | `main.py` |
| Existing Ollama provider integration | `core/providers/` |
| Runtime contract and acceptance | `docs/LOCAL_MODEL_RUNTIME.md` |

Exact file names under `core/runtime/` are defined by the implementation and its module contract; do not assume every future adapter must copy Ollama's internals.

## 5. Lifecycle and safety invariants

- `installed` does not mean `loaded`.
- `loaded` does not mean inference succeeded.
- Catalog reachability does not mean runtime readiness.
- A runtime already started by the user is not owned by the application.
- The application may stop only a process it started and owns.
- Missing telemetry is `unknown`, not zero or success.
- A failed load/unload must retain the last trustworthy observed state.
- No model download or automatic eviction occurs in this phase.
- No cloud fallback is triggered implicitly by local runtime failure.

## 6. Acceptance criteria

Phase 3 software implementation is accepted when:

- Runtime Manager is provider-neutral.
- Ollama is isolated behind Runtime Adapter.
- Runtime and model lifecycle states are distinct and accurately observed.
- Status, snapshot, inventory, and inspection are read-only.
- Load/unload are explicit, bounded POST operations with state verification.
- Process ownership prevents stopping externally started processes.
- Runtime lifecycle persistence is separate from catalog and inference status.
- Failures are normalized, bounded, and persisted without destroying last-known-good observations.
- The full deterministic test suite and CI checks pass.
- Hardware validation limitations are recorded without misclassifying them as code defects.

## 7. Completion record and environment limitation

**Software status:** Completed and merged through PR #7, merge commit `d30621e85f7f58096f57cf0e40f7dace23a60b21`.

The PR CI run recorded 109 passing tests. Python compilation and frontend JavaScript syntax validation passed. Windows smoke validation confirmed local Ollama connectivity, runtime readiness, installed-model inventory, model inspection, and process-ownership safety.

An explicit load attempt for `qwen2.5-coder:0.5b` failed in the observed machine environment. The machine had 4 GB RAM while Chrome and VS Code were active and used a mechanical HDD. The model remained installed and unloaded; runtime readiness and inventory remained healthy. Larger models were deliberately not attempted to avoid memory pressure and possible system unresponsiveness. The HDD/pagefile is not a practical substitute for RAM under sustained paging.

This result is recorded as hardware-constrained/inconclusive for successful live model loading, not as a demonstrated software defect. Unload was not attempted because the model never reached loaded state. Successful live load/unload on adequately provisioned hardware remains unverified.

**Important:** Do not repeat load attempts or test larger models on the constrained machine. Revisit live lifecycle validation only when sufficient hardware resources are available.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 3 — Local Model Runtime

**Mandatory instruction:** This execution plan must be followed precisely for Local AI Assistant, Phase 3. Preserve process-ownership safety, bounded lifecycle operations, state-verification semantics, and the separation between runtime, catalog, and inference status. Never convert an environment-limited validation result into a claim of success or a software defect without evidence. Do not run resource-intensive local model tests on hardware known to lack sufficient headroom.
