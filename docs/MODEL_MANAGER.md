# Model Manager

**Status:** Accepted target contract; operator profiles and local capability manifests exist, persistent model records are not implemented.

## 1. Purpose
Model Manager owns normalized model records and their lifecycle. Interface Manager currently exposes provider catalogs and live discovery; persistent catalog history and a scheduled Updater are later increments.

## 2. Model record
A normalized record should include:
- stable `provider_id` and exact `model_id`;
- display name and provider-reported description when available;
- modalities, context/output limits, streaming, tool calling, structured output, and supported task endpoints;
- pricing/free-tier eligibility with source and checked timestamp;
- account visibility and discovery source;
- lifecycle state, first/last seen timestamps, and last successful probe;
- evidence class and confidence for each capability field.

Unknown values must be nullable/unknown, not filled with guessed defaults.

## 3. Evidence hierarchy
- `provider_declared`: provider-wide statement.
- `catalog_reported`: model-specific catalog metadata.
- `curated_manifest`: maintained local knowledge with a source.
- `runtime_observed`: response metadata or observed API behavior.
- `experimentally_verified`: controlled task test with recorded method/result.
- `unknown`: no reliable evidence.

Provider-level task tags are hints only; they do not automatically become model-level guarantees.

## 4. Lifecycle
Supported states include:
- discovered
- metadata_pending
- needs_validation
- tested
- active
- unavailable
- deprecated
- retired

A failed request does not immediately mean a model is retired. Authentication, permission, quota, network, and provider incidents must be distinguished.

## 5. Updater boundary
Updater discovers and stages proposed changes. It does not directly mutate the operational catalog or user-selected model. Validation compares source, schema, timestamps, and material changes before applying a catalog update. The user is informed before a selected model is replaced.

## 6. Task matching
Task matching should evaluate model-level evidence, modalities, context/output bounds, tool requirements, account availability, health, quota, and user policy. Provider-level tags can narrow candidates but cannot certify eligibility.

## 7. Acceptance criteria for persistent Model Manager
- Versioned catalog schema and migration.
- Last-known-good catalog retained across network failures.
- Added/changed/unavailable/deprecated/removed change sets.
- Provenance and evidence retained per field.
- No silent change to active provider/model.
- Tests prove unknown data stays unknown and discovery cannot bypass validation.
