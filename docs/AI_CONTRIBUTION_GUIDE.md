# AI-Assisted Development and Delegation Guide

**Status:** Required guidance for Mistral, Claude, and other AI coding agents.

This document is a project-specific execution contract. It supplements the task prompt; it does not replace the project principles or module specifications.

## 1. Read before acting

Before proposing or changing code, read:
1. `PROJECT_PRINCIPLES.md`
2. `ARCHITECTURE.md`
3. `ROADMAP.md`
4. The task's relevant module contract(s)
5. The current implementation and related tests

Do not rely only on a pasted excerpt if repository files are available.

## 2. Establish the truth

Before implementation, report:
- current branch and working-tree state;
- relevant files and existing behavior;
- which requested behavior is already implemented;
- which parts are missing;
- conflicts between the task and documentation;
- proposed files to change.

Never describe planned architecture as existing code. Never claim a test passed unless it was actually run and its result observed.

## 3. Respect boundaries

- Do not introduce provider-specific dependencies into domain modules.
- Do not bypass repositories or permission checks.
- Do not allow models to authorize or directly execute tools.
- Do not ingest conversations/files without explicit source permission.
- Do not publish Librarian reports without explicit user approval.
- Do not merge model-private memories without authorization.
- Do not replace original files with extracted or generated content.
- Do not make an external connector a mandatory dependency.
- Do not introduce speculative schema tables unrelated to the approved task.

## 4. Change discipline

- Implement only the requested scope.
- Prefer small changes and preserve existing behavior.
- Do not rename, delete, or broadly refactor unrelated files.
- Do not add dependencies without explaining why and evaluating alternatives.
- Do not change secrets, local settings, or user data.
- Do not modify GitHub branch protection, merge, release, or deployment settings unless explicitly requested.
- Never commit API keys, tokens, local databases, chat history, or ignored settings.

## 5. Tests and documentation

- Add or update focused tests for changed behavior.
- Run the relevant test suite and report exact commands/results.
- Update module documentation and README when user-visible behavior changes.
- Keep implementation status accurate.
- Document limitations and unverified behavior explicitly.
- Do not suppress failing tests or weaken assertions merely to get a green run.

## 6. Required completion report

At the end, provide:
1. Summary of changes.
2. Files changed and why.
3. Tests run and exact outcomes.
4. Known limitations or unverified assumptions.
5. Any architectural conflict requiring owner approval.
6. Suggested next step, without performing it automatically.

## 7. Stop conditions

Stop and ask the project owner before proceeding if:
- the task conflicts with a non-negotiable principle;
- required permissions or data scope are unclear;
- the task would expose private data to a cloud provider;
- a migration may delete or irreversibly transform user data;
- a requested capability cannot be implemented within the documented module boundary;
- a task prompt asks you to silently change architecture or skip required validation.
