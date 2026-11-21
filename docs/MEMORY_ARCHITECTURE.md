# Memory and Knowledge Architecture

**Status:** Accepted logical model; implementation is planned incrementally.

## 1. Purpose

The application distinguishes conversation history, model-private memory, source material, working analysis, and approved shared knowledge. These categories have different ownership, retention, and permission rules.

## 2. Memory categories

### 2.1 Conversation history

Conversation sessions, messages, and execution events are persistent application records. They are not automatically training data and are not automatically ingested into the Librarian.

A conversation or selected portion may be made available to the Librarian only after explicit source ingestion permission.

### 2.2 Model-private memory

Each model may have logically isolated memory associated with its model identity and owner/scope. Logical isolation does not require a separate physical database.

- Model A cannot read Model B's private memory by default.
- Sharing or transferring memory requires explicit authorization.
- Memory entries should carry provenance, timestamps, lifecycle state, and deletion/retention policy.
- Model identity must be stable enough to avoid accidental memory crossover when provider model IDs change.

### 2.3 Shared Approved Knowledge

The application provides a common knowledge layer for authorized modules and models. It contains user-approved reference material and derived knowledge with traceable provenance.

Shared knowledge is not a universal memory dump. Access remains permission-controlled and may be scoped by project, source, dataset, or sensitivity.

### 2.4 Librarian working data

The Librarian's extracted text, metadata, intermediate analysis, and draft reports remain in its private workspace until publication approval. They are not equivalent to model-private memory or Approved Knowledge.

## 3. Librarian knowledge states

1. **Librarian Workspace:** private working artifacts and intermediate outputs.
2. **Review & Approval:** validated report versions awaiting user decision.
3. **Approved Knowledge:** user-approved artifacts available to authorized consumers.

These are logical states/scopes in the shared data system, not mandatory separate databases.

## 4. No automatic ingestion

- Do not ingest every conversation by default.
- Do not scan every project or file automatically without a grant.
- Do not treat model responses as verified facts.
- Do not publish reports or summaries into Approved Knowledge without explicit user approval.
- Retain source locators and distinguish direct evidence from model inference.

## 5. Retrieval and training data are different

RAG/knowledge retrieval uses source-linked content to answer queries. A training dataset is a separate curated artifact requiring its own cleaning, licensing, privacy, deduplication, labeling, and approval pipeline.

An approved Librarian report is not automatically suitable for model training. Preserve provenance so a separate future dataset pipeline can be built without conflating the two systems.

## 6. Lifecycle and deletion

Memory records need explicit retention and deletion behavior. Deleting a conversation, source, or permission grant must not cause ambiguous cascade behavior. The system should identify dependent derived artifacts and apply the user's configured policy.

Related: [PERMISSIONS.md](PERMISSIONS.md), [DOCUMENT_INGESTION.md](DOCUMENT_INGESTION.md), [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).
