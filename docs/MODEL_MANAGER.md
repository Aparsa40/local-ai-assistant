# Model Manager and Catalog

**Status:** Accepted target responsibilities; current capability metadata is an initial foundation.

## 1. Purpose

Model Manager maintains the application's normalized view of models independently from provider adapters. It supports model discovery, metadata, capability evidence, user selection, lifecycle status, and safe catalog updates.

Model Manager does not execute inference; Interface Manager does that through provider adapters.

## 2. Model identity

A model entry must be identified by at least:
- stable internal model record ID;
- provider ID;
- exact provider model ID;
- display name (optional and non-authoritative);
- catalog source and last-seen time.

The exact provider model ID must be preserved for API calls. Display names and aliases must never be used as substitutes for exact IDs.

## 3. Metadata categories

Potential metadata includes:
- model family/version and publisher;
- supported modalities;
- context and maximum output limits;
- streaming and tool/function calling;
- structured output;
- task suitability labels;
- embedding/reranking role;
- lifecycle state (available, deprecated, retired, unknown);
- account/configuration availability;
- pricing/free-tier facts and quota semantics;
- verification source, confidence, and last-checked timestamp.

Do not store an inferred capability as a verified fact. Each capability should carry an evidence class such as provider-reported, catalog-reported, curated, experimentally verified, or unknown.

## 4. Capability labels

Labels should be typed, versionable, and composable. Initial task labels may include:
- `general_chat`
- `coding`
- `analysis`
- `translation`
- `summarization`
- `document_extraction`
- `vision`
- `tool_use`
- `embedding`
- `reranking`

A label describes suitability, not a guarantee of quality. Preserve the distinction between task suitability and technical capability.

## 5. User selection

- Store the selected provider and exact model ID in the appropriate user/profile/conversation scope.
- Preserve user selections when refreshing a catalog.
- If a selected model disappears or becomes deprecated, mark the selection as needing attention; do not silently substitute another model.
- Any automatic substitution must follow an explicit user-approved policy and be visible in the UI.

## 6. Catalog update boundary

Model & Provider Updater obtains fresh metadata from supported provider sources. Model Manager validates, normalizes, compares, and stores the resulting catalog changes.

A refresh should produce a change set:
- added models;
- changed metadata/capabilities;
- deprecated or retired models;
- temporarily unavailable models;
- removed/unknown entries;
- changes to pricing/free-tier metadata.

The UI should show when an update is available and what will change. A disabled refresh/update action must not be presented as if it were silently checking or updating in the background; its actual behavior must be documented and tested.

## 7. No fabricated certainty

- A provider's published allowance is not a live remaining balance.
- Missing context length is unknown, not unlimited.
- Tool support at provider level does not imply support for every model.
- Free-tier eligibility is time-sensitive and account-dependent.
- Recommendations must be based on current evidence and display uncertainty.

Related: [PROVIDER_SYSTEM.md](PROVIDER_SYSTEM.md), [INTERFACE_MANAGER.md](INTERFACE_MANAGER.md), [ROADMAP.md](ROADMAP.md).
