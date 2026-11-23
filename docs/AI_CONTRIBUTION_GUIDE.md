# AI Contribution and Delegation Guide

**Status:** Accepted engineering workflow.

## 1. Read before changing code
Read the relevant documents in this order:
1. PROJECT_PRINCIPLES.md
2. ARCHITECTURE.md
3. ROADMAP.md
4. The module contract being changed (for example INTERFACE_MANAGER.md or AGENT_RUNTIME.md)
5. OPERATOR_CATALOGS.md when changing provider discovery or quota behavior.

Inspect the current implementation and tests before proposing a replacement.

## 2. Required work plan
Before implementation, identify:
- the owning module and its non-responsibilities;
- current behavior versus accepted design;
- public/internal contracts and affected callers;
- data ownership and security implications;
- failure modes and acceptance tests;
- documentation that must change.

## 3. Implementation rules
- Work only on the requested branch and do not merge unless explicitly asked.
- Do not bypass checks, weaken assertions, delete tests, or suppress errors to make CI green.
- Do not invent model IDs, quotas, capability values, or provider behavior.
- Preserve exact model IDs and user settings.
- Use bounded network operations and safe errors.
- Do not add speculative database tables before their owning workflow exists.
- Do not claim live provider validation unless real credentials and requests were actually tested.

## 4. Validation
Run the repository's full CI-equivalent checks:
- `node --check static/app.js`
- `python -m compileall -q core main.py`
- `python -m pytest -q`

Add focused tests for new behavior and regressions. Report the exact test count and any environment limitations. A pending GitHub Actions run is not a passing result.

## 5. Delivery
Summarize changed files, architectural impact, tests/checks, known limitations, and the resulting commit/PR state. Never merge a PR or change branch protections unless explicitly authorized.
