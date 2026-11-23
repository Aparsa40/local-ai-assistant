# Catalog Storage Schema

**Status:** Implemented incrementally in the Interface Manager foundation.

## Ownership and source of truth

- Version-controlled operator manifests under `core/providers/` are the editable source of truth for provider-level facts and curated model profiles.
- SQLite is the operational read store shared by the UI and internal services.
- Live model IDs are sourced from successful provider API discovery and are never authored into operator manifests.
- Runtime status and quota observations are separate from catalog facts.

## Tables

| Table | Identity | Purpose |
| --- | --- | --- |
| `operator_catalogs` | `provider_id` | Persisted operator manifest, service metadata, discovery policy, documentation, and free-tier caveats. |
| `operator_model_profiles` | `provider_id + model_id` | Curated model capability evidence maintained in the repository. |
| `live_model_catalog` | `provider_id + model_id` | Exact model IDs discovered from a provider, safe provider-reported model metadata, source, active state, and first/last-seen timestamps. |
| `provider_runtime_status` | `provider_id` | Latest catalog reachability probe, safe diagnostic, and local process-start ownership details. |
| `model_runtime_status` | `provider_id + model_id` | Observed inference availability, last successful request, last error, and observed limits. |
| `provider_quota_snapshots` | generated ID | Time-stamped provider quota/usage responses. |
| `catalog_sync_history` | generated ID | Successful, failed, and ambiguous-empty catalog synchronization outcomes. |
| `provider_intelligence_reports` | generated ID | Bounded per-provider runtime/offline analysis snapshots with source timestamps, evidence, task suitability, and schema version. |

## Lifecycle

1. `init_db()` creates missing tables without replacing existing chat/session/profile data.
2. Startup seeds/upserts operator manifests and curated profiles from repository-owned source files.
3. UI reads the last persisted catalog; ordinary reads do not call provider APIs.
4. Save & Connect reuses the model IDs already returned by its catalog reachability probe and persists them. For Ollama, the Intelligence service first probes the configured endpoint and may start the installed CLI only for an unreachable loopback HTTP endpoint when auto-start is enabled.
5. Manual refresh calls the provider adapter explicitly and stores the new result only after successful discovery.
6. Failed syncs do not deactivate or delete previous models. Empty responses with a prior catalog are treated as ambiguous and preserve the last known-good active set.
7. Inference success/failure updates model runtime status independently of the model's static capabilities.
8. Runtime reports are generated from fresh observations. Offline reports read SQLite only and label stale/unknown observations rather than asserting current reachability.
9. Report history is capped at 20 snapshots per provider and report type; catalog tables remain the source of truth.

## Evidence rules

- A provider-reported model ID proves only that the ID appeared in the discovery response.
- Ollama model size, family, parameter size, quantization, context metadata, and capabilities are retained only when returned by its local tags/show APIs.
- Task suitability is `supported` only when provider/model metadata directly reports the capability; curated hints produce `likely`; absent evidence remains `unknown`.
- A curated model profile is a repository-maintained reference, not proof that the user's account can invoke that model.
- Model runtime availability stays `unknown` until an inference request is actually observed.
- Provider quota allowance, account usage, and remaining balance are distinct. Missing remaining balance stays unknown.
- Provider-level telemetry is not copied into model-level status unless the provider response identifies the model.

## Operational read model

`GET /api/operational-report` aggregates persisted operator manifests, live model records, provider diagnostics, model runtime observations, quota snapshots, and sync history. `GET /api/intelligence/reports/latest` reads the latest saved analysis, while `POST /api/intelligence/reports/offline` builds and persists a report exclusively from SQLite. Supervisor/Orchestrator integration can consume these read models later without directly calling provider APIs.
