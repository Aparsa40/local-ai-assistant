# Phase 2 — Interface Manager

**Project:** Local AI Assistant  
**Phase:** 2 of 11  
**Document type:** Authoritative execution plan  
**Status:** Completed — PR #6 merged  
**Branch delivered:** `feat/interface-manager`  
**Merge commit:** `2657b41e3fec1675b29e1612c358e6583ebfb137`  
**Pull request:** [#6](https://github.com/Aparsa40/local-ai-assistant/pull/6)  
**Last reviewed:** 2026-11-24

## 1. Purpose

Establish one provider-neutral control plane between application workflows and online/local model providers. Internal modules must not need to know vendor SDKs, provider-specific request payloads, or adapter implementation details.

Interface Manager is infrastructure. It is not an agent, task planner, permission authority, or response fact-checker.

## 2. Scope

### In scope

1. Define provider adapter and registry boundaries.
2. Expose provider listing and capability metadata.
3. Expose provider/operator catalog information separately from live model discovery.
4. Discover exact model identifiers through bounded provider operations.
5. Normalize connection diagnostics and safe errors.
6. Expose quota/usage information only when supported by authoritative observations.
7. Route chat streaming through the service boundary.
8. Preserve selected provider/model behavior and avoid silent model replacement.
9. Persist operator/live catalog information and operational observations where implemented.
10. Document current limitations and future contract gaps.

### Out of scope

- Automatic task-based model routing.
- Agent planning or Supervisor behavior.
- Local model process lifecycle control; that belongs to Phase 3.
- Encrypted credential vault.
- Complete Model & Provider Updater and scheduled refresh.
- Full normalized inference event envelope, generalized retries, and fallback orchestration.
- Conversation Memory, Context Manager, or Knowledge Storage.

## 3. Execution steps

### Step 2.1 — Audit existing provider integrations

- Inventory provider adapters, registry behavior, configuration, chat orchestration, and tests.
- Identify provider-specific logic leaking into application/API/UI layers.
- Preserve current provider IDs, exact model IDs, and user-selected provider/model settings.
- Record compatibility constraints before changing callers.

**Deliverable:** provider integration inventory and compatibility baseline.

### Step 2.2 — Define provider-neutral adapter contracts

- Define stable provider identity and adapter lifecycle.
- Standardize model discovery and chat streaming entry points.
- Keep provider SDK calls and provider-specific payload parsing inside adapters.
- Normalize expected errors without returning secrets or raw sensitive exception text.
- Ensure unsupported or unknown capability values remain unknown.

**Deliverable:** provider adapter contract and registry boundary.

### Step 2.3 — Implement Interface Manager service

Implement the service boundary for:
- listing registered providers;
- retrieving provider capability metadata;
- reading operator catalog metadata;
- discovering live model IDs through bounded adapter calls;
- checking catalog reachability;
- retrieving supported quota telemetry;
- streaming chat through the selected adapter.

The service must not silently select a different provider or model.

**Deliverable:** provider-neutral Interface Manager service.

### Step 2.4 — Separate operator catalog from live model catalog

- Keep repository-maintained provider metadata separate from provider-reported exact model IDs.
- Label curated capability hints and provider-level facts as evidence, not account/model guarantees.
- Preserve exact live model identifiers.
- Keep ordinary UI reads local/persisted; live network discovery must be an explicit action.
- Preserve last-known-good catalog data after failed or ambiguous-empty refreshes.

**Deliverable:** evidence-aware provider/model catalog behavior.

### Step 2.5 — Add bounded diagnostics and quota visibility

- Bound network timeouts and discovery work.
- Distinguish catalog reachability from inference success.
- Redact credentials and sensitive provider details.
- Expose quota only when an authoritative API or observed response headers support it.
- Keep unknown balances and limits unknown.
- Distinguish provider-level telemetry from model-specific observations.

**Deliverable:** safe diagnostics and honest quota reporting.

### Step 2.6 — Integrate API and chat orchestration

- Route provider discovery and chat streaming through Interface Manager.
- Expose provider-neutral API responses.
- Keep provider-specific adapter construction out of UI/API handlers.
- Preserve existing manual provider/model selection.
- Avoid introducing autonomous routing at this stage.

**Deliverable:** application integration using the service boundary.

### Step 2.7 — Persist catalog and operational read models

The delivered foundation includes SQLite/SQLAlchemy records for:
- operator manifests and curated model profiles;
- live provider model catalog;
- provider runtime/catalog reachability observations;
- model inference availability observations;
- quota snapshots;
- catalog synchronization history;
- bounded provider intelligence reports.

Keep these domains distinct. Catalog presence does not prove inference availability; a successful catalog probe does not prove inference health.

**Deliverable:** persistent catalog and operational read models, as documented in `docs/CATALOG_STORAGE.md`.

### Step 2.8 — Test and deliver

- Add isolated Interface Manager contract tests.
- Test provider registry behavior, discovery, error normalization, credential redaction, and chat delegation.
- Run Python compilation, frontend JavaScript syntax validation, and the full pytest suite.
- Verify that existing chat/provider behavior remains compatible.
- Update module documentation, architecture snapshot, roadmap, and README as needed.
- Deliver through a pull request and merge only after the required checks pass and merge is explicitly authorized.

**Deliverable:** merged, tested Interface Manager foundation.

## 4. Main implementation map

| Area | Repository location |
|---|---|
| Interface Manager service | `core/interface_manager.py` |
| Provider adapter contract | `core/providers/base.py` |
| Provider registry | `core/providers/registry.py` |
| Capability metadata | `core/providers/capabilities.py` |
| Operator catalog manifests | `core/providers/operator_catalog.py` |
| Application API boundary | `main.py` |
| Existing chat orchestration | `core/orchestrator.py` |
| Catalog persistence | `core/catalog_storage.py` |
| SQLAlchemy models and SQLite setup | `core/database.py` |
| Service tests | `tests/test_interface_manager.py` |
| Module contract | `docs/INTERFACE_MANAGER.md` |
| Catalog persistence contract | `docs/CATALOG_STORAGE.md` |

This map records the delivered implementation; it is not permission to refactor unrelated modules during later phases.

## 5. Implemented service surface

The delivered service contract includes:
- `list_providers()`
- `get_capabilities(provider_id)`
- `get_provider_catalog(provider_id)`
- `get_quota_status(provider_id)`
- `list_models(provider_id)`
- `check_connection(provider_id)`
- `stream_chat(provider_id, messages, model)`

The HTTP surface documented by the module contract includes provider listing, capabilities, catalogs, persisted model reads, explicit catalog sync, quota, connection diagnostics, operational reports, intelligence report reads/generation, and chat streaming.

The connection diagnostic is a model-catalog probe, not an end-to-end inference health check. For local Ollama, process startup behavior is bounded by the configured loopback/auto-start policy; local model lifecycle control itself belongs to Phase 3.

## 6. Acceptance criteria

Phase 2 is accepted when:

- Internal application code can list providers, read capabilities/catalogs, discover models, and stream chat through Interface Manager.
- Provider SDK and payload details remain inside adapters.
- Provider/model identifiers and existing user choices are preserved.
- Live discovery is explicit and bounded; normal reads use persisted data.
- Failures do not erase last-known-good model catalog records.
- Catalog reachability, inference availability, and quota are not conflated.
- Secrets and raw sensitive provider errors are not exposed.
- Tests cover service behavior and existing regression checks remain green.
- Documentation accurately separates implemented behavior from future work.

## 7. Completion record

**Status:** Completed and merged.

PR #6 was merged into `main` with merge commit `2657b41e3fec1675b29e1612c358e6583ebfb137`. This is the completion evidence for the Phase 2 Interface Manager delivery.

The document does not claim that the encrypted credential vault, automatic routing, full Model Manager, scheduled Updater, or generalized inference retry/fallback policies are complete.

## 8. Execution directive

**Project:** Local AI Assistant  
**Phase:** 2 — Interface Manager

**Mandatory instruction:** This execution plan must be followed precisely for Local AI Assistant, Phase 2. Preserve the provider-neutral boundary, exact provider/model identifiers, user selections, safe diagnostics, and catalog evidence rules. Any future extension must maintain the acceptance criteria and must not move Agent Runtime, autonomous routing, or local lifecycle responsibilities into Interface Manager.
