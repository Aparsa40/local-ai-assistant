# Provider & Model Intelligence

**Status:** First implementation committed; pending CI validation and local Ollama smoke testing.

### Implemented in the current increment

- Ollama startup/reuse is coordinated during explicit POST connection or catalog-sync actions; opening Settings remains side-effect free.
- Local startup is restricted to loopback HTTP endpoints, uses the installed Ollama CLI with shell execution disabled, and records process ownership only for processes started by this application.
- Ollama discovery enriches live tags with size, digest, model family, parameter size, quantization, context metadata, and provider-reported capabilities.
- Live metadata is persisted in the existing live-model catalog; partial enrichment does not erase prior metadata.
- Runtime and offline report snapshots are stored in SQLite with bounded per-provider/type history.
- Read-only latest-report and SQLite-only offline-report API endpoints are exposed, with a minimal Settings UI summary.
- Automated tests cover lifecycle decisions, metadata parsing, report persistence, API access, and the offline no-network/no-subprocess contract.

The code is not considered complete until CI passes and the user verifies Ollama startup against their installed Windows runtime.

## 1. Purpose

Provider & Model Intelligence is the shared operational analysis and reporting capability for cloud providers and local model runtimes. It coordinates provider checks, local-runtime startup when explicitly requested, model discovery, evidence-aware capability analysis, and durable reports.

It is one subsystem with small internal responsibilities. It is **not** a new autonomous agent, a second provider registry, or a replacement for Interface Manager.

The first implementation must deliver two outcomes:

1. When the user activates local Ollama, the application detects an existing server or safely starts one, discovers installed models, and reports the result.
2. For every provider, the application can produce a fresh runtime report and an offline report from the latest persisted snapshot.

## 2. Ownership boundaries

### Provider & Model Intelligence owns

- Orchestrating a bounded provider-intelligence refresh.
- Requesting provider diagnostics and model discovery through Interface Manager.
- Coordinating Ollama startup only when the configured endpoint is local and auto-start is enabled.
- Enriching discovered model IDs with provider-reported metadata.
- Producing evidence-aware capability and task-suitability assessments.
- Generating runtime/offline reports, persisting them, and exposing read-only report views.
- Reporting freshness, unknown values, partial results, and failures explicitly.

### Interface Manager owns

- Provider registry and adapter construction.
- Provider-specific API communication, model discovery, quota reads, and inference streaming.
- Provider-neutral errors and bounded request timeouts.
- No task-level model ranking or report-persistence policy.

Intelligence must not import provider adapters directly or duplicate provider API implementations. It calls Interface Manager's service boundary. Ollama process lifecycle is the one local-runtime operation coordinated internally by Intelligence because it is an operating-system process, not a provider API request.

### Storage owns

- Durable catalog, runtime observations, sync history, and report snapshots.
- No network calls, process startup, or model scoring.

### UI and future agents

- UI reads persisted reports and starts an explicit refresh.
- Future Supervisor/Agent Runtime consumers read the same report contract.
- Agents must not call provider APIs to reconstruct facts already available through this subsystem.

## 3. Internal components

These are implementation responsibilities within one subsystem, not separately deployed services:

| Component | Responsibility |
| --- | --- |
| Intelligence Service | Coordinates refresh, analysis, report generation, and persistence. |
| Local Runtime Controller | Detects and starts Ollama safely; owns only processes it launched. |
| Model Metadata Collector | Gets model details through Interface Manager/provider adapters. |
| Capability & Suitability Analyzer | Normalizes evidence and produces cautious task recommendations. |
| Report Builder | Builds runtime/offline report documents from collected or persisted facts. |
| Report Repository | Stores and retrieves report snapshots through SQLAlchemy storage functions. |

The Local Runtime Controller initially supports Ollama only. Do not build a generic process-supervisor framework before a second real runtime requires it.

## 4. Ollama activation and lifecycle

### Trigger

Starting Ollama is an explicit activation side effect, not a side effect of opening Settings or rendering the provider list.

The existing **Save and check connection** action is the initial trigger. A later dedicated activation/refresh action may call the same service operation.

### Safe startup algorithm

1. Read the saved Ollama base URL and runtime preferences.
2. Parse and validate the endpoint. Automatic process startup is allowed only for loopback hosts: localhost, 127.0.0.1, or ::1. A remote/LAN endpoint is probe-only; never start a local process for it.
3. Probe the configured API first. If it responds, reuse it and do not spawn another server.
4. If it does not respond and auto-start is enabled, locate an installed official Ollama CLI using PATH and a small set of documented platform-specific install locations. Do not recursively scan disks or execute arbitrary paths supplied by the browser.
5. Start the CLI as an argument array equivalent to ollama serve, with shell disabled, no shell interpolation, a bounded startup wait, and output redirected to a controlled diagnostic sink. Preserve Ollama's loopback default; do not expose the listener on a public interface.
6. Poll the API with a short interval until ready or until the startup deadline expires.
7. Once ready, discover models and persist the successful inventory. If startup or discovery fails, record a safe categorized error and preserve the last-known-good catalog.
8. Return a structured result describing whether the server was already running, started by this application, unavailable, or not installed.

### Process ownership and safety

- A successful API probe always takes precedence over process startup.
- Use an in-process async lock so simultaneous requests cannot start duplicate servers.
- Retain the process handle/PID for processes started by this application.
- Never terminate a process that the application did not start.
- Do not stop Ollama automatically when the user changes provider or closes Settings. Initial behavior is start/reuse only; explicit stop controls can be considered later.
- Do not use shell=True, command strings, user-controlled executable paths, or broad process-name termination.
- Startup timeout, missing executable, permission failure, port conflict, and API-not-ready are distinct safe error categories.
- If auto-start is disabled, report the service as offline and provide a clear instruction to start Ollama manually.

### Configuration

Add a small Ollama runtime preference under the existing provider configuration:

- auto_start: boolean, default true for local Ollama.
- startup_timeout_seconds: bounded internal/default value; not an unrestricted user-provided timeout in the first increment.

Do not add service installation, Windows registry mutation, firewall rules, startup-at-login registration, or system-wide environment-variable edits.

## 5. Model discovery and evidence

### Ollama sources

Use the official local API:

- GET /api/version (or the existing bounded readiness probe) to identify a responding server.
- GET /api/tags to enumerate locally installed model names and tag metadata.
- POST /api/show for each discovered model to obtain model details and capability metadata.
- GET /api/ps only for a separate observation of models currently loaded in memory; this is not proof of total machine capacity.

The current Ollama adapter returns only model IDs from /api/tags. Extend discovery without breaking the existing list_models() -> list[str] contract, for example through an additional typed metadata method exposed by Interface Manager.

### Evidence classes

Every capability/recommendation must identify its evidence:

- provider_reported: returned by the live provider API.
- curated_manifest: maintained in this repository.
- model_card: sourced from a verified model card or official model documentation.
- runtime_observed: observed through a real, bounded inference/tool/vision test.
- inferred: a cautious conclusion from metadata; never presented as verified.
- unknown: no reliable evidence.

Do not infer that a model supports vision, tools, structured output, or a task merely from its name or family. Provider-level support does not prove model-level support.

### Task suitability

The first version should report suitability for a small, stable task taxonomy:

- general chat and instruction following
- coding
- reasoning and analysis
- summarization
- translation
- vision / image understanding
- embeddings
- tool calling

For each model/task pair, return supported, likely, unsupported, or unknown, plus evidence, source, and confidence. Only use supported when direct model metadata or an actual runtime test supports the claim. Curated hints and model-card descriptions may produce likely, not verified support.

Do not run automatic benchmark suites or load every installed model during ordinary provider activation. They can consume significant RAM/VRAM and delay startup. A later, explicit evaluation workflow may add opt-in tests.

### Resource estimates

Record provider-reported model size, parameter size, family, quantization, and loaded-model memory observations when available. Do not estimate available host RAM/VRAM or promise that a model will fit unless the application has measured the relevant host resources and can state the estimation method. Missing values remain unknown.

## 6. Reports

### Runtime Intelligence Report

Generated after an explicit refresh. It includes:

- provider identity, endpoint scope (local/remote), runtime status, and probe time;
- whether Ollama was already running, started by this application, or not started;
- live model inventory and per-model metadata;
- model capability/task suitability with evidence and confidence;
- model runtime observations, if any;
- cloud-provider quota information, preserving the distinction between published allowance, observed usage, and remaining balance;
- warnings, partial failures, and last-known-good data references;
- generated time, source observation times, and freshness/age.

A report may be healthy, degraded, unavailable, or unknown. Partial model-metadata failures must not invalidate a successfully discovered inventory.

### Offline Intelligence Report

Generated exclusively from SQLite. It must not:

- make provider API calls;
- start or stop Ollama;
- refresh catalogs or quota;
- claim that a previously reachable provider is reachable now.

It reports the last persisted observations, their original timestamps, and freshness labels such as fresh, stale, or unknown. It may analyze stored metadata, but must label every conclusion as based on the last stored snapshot.

### Report schema

Add one report table rather than duplicating existing catalog tables:

**provider_intelligence_reports**

- id: primary key
- provider_id: provider identity; nullable only if a deliberately global report is needed
- report_type: runtime or offline
- generated_at: UTC timestamp
- source_snapshot_at: newest source observation represented by the report
- overall_status: normalized status
- summary: short human-readable summary
- report_data: JSON document with models, evidence, findings, and provenance
- schema_version: report document version

Keep a bounded history (initial target: latest 20 reports per provider/type). Do not copy the full raw provider catalog into every report when stable catalog records can be referenced; store analysis and source identifiers/timestamps needed to interpret it.

Existing operator_catalogs, operator_model_profiles, live_model_catalog, provider_runtime_status, model_runtime_status, provider_quota_snapshots, and catalog_sync_history remain authoritative for their current facts. Reports are derived snapshots, not replacements.

## 7. API and UI contract

Prefer extending the current settings workflow rather than adding parallel discovery paths.

Target operations:

- Existing POST /api/providers/{provider_id}/connection: for Ollama, coordinate local startup when permitted, then probe and persist discovered model IDs; return runtime-start details in a normalized field.
- Existing POST /api/providers/{provider_id}/catalog/sync: explicit catalog refresh; it must not bypass the same Ollama readiness/start policy.
- GET /api/intelligence/reports/latest?provider_id=...: read the latest persisted report; no network or process side effects.
- POST /api/intelligence/reports/offline: generate and persist an offline report from SQLite only.
- GET /api/operational-report: retain compatibility; it may later expose a link/summary to the latest intelligence report.

The UI should show a concise runtime state, model count, last refresh time, and report summary. Model cards may expose details and evidence on expansion. Do not build a large dashboard in this increment.

## 8. Storage and failure semantics

- Persist a new report only after a report document has been successfully assembled.
- A failed refresh must not overwrite or delete the previous successful report.
- A failed/empty/partial discovery must preserve the last-known-good model inventory according to the existing catalog sync rules.
- Record failure in existing runtime/sync history and include it in the report result where possible.
- Never store API keys, environment values, raw process environment, full unfiltered stderr, or secrets in report JSON.
- Keep all timestamps UTC and preserve the existing naive-UTC SQLite storage contract.

## 9. Bounded implementation plan

### Increment A — Design and contracts

- This document defines ownership, flows, evidence, report types, safety rules, and exit criteria.
- Confirm no duplicate provider/model catalog or separate runtime-manager service is introduced.

### Increment B — Ollama lifecycle and rich discovery

- Add safe local endpoint detection and process startup.
- Add readiness polling, concurrency protection, bounded timeout, and process ownership tracking.
- Add /api/show metadata while preserving existing adapter callers.
- Persist metadata in the existing live catalog JSON field.

### Increment C — Report generation and persistence

- Add the report table/repository functions.
- Generate runtime reports from fresh observations and offline reports from SQLite only.
- Expose latest-report read API and a minimal settings UI summary.

### Increment D — Validation and close

- Add deterministic unit tests for process startup, existing-server reuse, remote endpoint no-start, disabled auto-start, timeout, missing executable, duplicate-start prevention, metadata parsing, and safe errors.
- Add report tests for runtime/offline generation, persistence, stale data, partial discovery, and preserving the previous report on failure.
- Prove the offline path makes no HTTP or subprocess calls.
- Run the complete existing test suite without removing, skipping, or weakening tests.

## 10. Explicit non-goals for this increment

- No autonomous AI agent that judges model quality.
- No benchmark suite or automatic model loading.
- No model download/pull, delete, or update management.
- No generic process manager for arbitrary local runtimes.
- No service installation, OS startup registration, firewall or registry changes.
- No automatic model routing or silent replacement of the user's selected model.
- No full event-sourcing/logging platform or large monitoring dashboard.
- No Supervisor, Agent Runtime, or Librarian implementation in this increment.

## 11. Exit criteria

This increment is complete when:

1. Selecting and explicitly connecting Ollama reuses an existing server or starts one safely when allowed.
2. Remote Ollama endpoints are never started locally.
3. Installed models and available metadata are discovered and persisted without losing prior good data on failure.
4. Runtime and offline reports are persisted and distinguish current observations from stale snapshots.
5. Task suitability is evidence-aware and unknown remains unknown.
6. UI and API expose the report without duplicating provider logic.
7. All new and existing tests pass without warnings introduced by this increment.

At that point, close this bounded Interface Manager/Intelligence increment and proceed to Local Model Runtime. Do not expand this phase into autonomous evaluation, routing, or agent orchestration.
