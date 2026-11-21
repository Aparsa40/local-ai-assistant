# Versioning Policy

The project follows Semantic Versioning (SemVer): `MAJOR.MINOR.PATCH`.

- **MAJOR:** incompatible public API changes, breaking data migrations, or major architectural changes requiring user action.
- **MINOR:** backward-compatible user-facing capabilities or substantial additive functionality.
- **PATCH:** backward-compatible fixes, security updates, documentation corrections, and small improvements.

## Pre-1.0 development

Before `1.0.0`, the project may use `0.MINOR.PATCH` releases. Public APIs and internal module contracts may evolve, but database migrations must still protect existing user data.

Do not assign fixed feature promises to a version number before the corresponding scope and acceptance criteria are approved. The roadmap defines dependencies and milestones; release versioning is decided when a milestone is sufficiently scoped.

## Release requirements

A release should include:
- updated version metadata where applicable;
- CHANGELOG entry;
- tests and CI results;
- migration notes for schema changes;
- documentation updates;
- known limitations and upgrade/backup guidance.

## Compatibility

- Database schema changes must use versioned migrations.
- Breaking changes to persisted data require a backup/recovery plan.
- Provider model IDs and external service catalogs are operational data and must not be treated as stable public APIs.
- Document status must distinguish implemented functionality from planned architecture.

## Version history

Record release-specific changes in the repository's `CHANGELOG.md`. This document defines the policy, not a speculative release schedule.
