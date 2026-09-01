# ADR-0005: CI reusable-workflow wiring for build.yaml

- **Status:** Superseded by ADR-0007
- **Date:** 2026-08-30
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** GitHub Actions overlay (prefer composite/reusable workflows over copy-paste; correct wiring), Core §2 reuse

> **Superseded by [ADR-0007](0007-pr-verification-topology.md) (2026-09-01).** The wiring
> below was never built. This ADR describes `build.yaml` orchestrating `build-package.yaml`
> and `build-container.yaml` with `secrets: inherit`; what shipped is a fork-safe
> pull-request adapter over a single secret-free reusable verifier. Do not treat the
> Decision below as current — it is retained for the reasoning that led to ADR-0007.

## Context

Review finding #4 (BLOCKER): `.github/workflows/build.yaml` (triggered on push to
`master`/`main` and on `v*` tags) invokes `uses: ./.github/actions/build-package.yaml` and
`uses: ./.github/actions/build-container.yaml` as **steps** inside a single job. That path
does not exist (`.github/actions/` is absent), and GitHub Actions reusable-workflow calls
must be **job-level** `uses:` pointing at `.github/workflows/*.yaml` files — which is where
`build-package.yaml` and `build-container.yaml` actually live. As written, the pipeline
cannot run.

Additionally, `build-package.yaml` currently declares `on: release: types: [published]`
rather than `on: workflow_call`, so it is not even shaped as a callable reusable workflow
today — it was designed to run standalone on a GitHub Release event.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Fix `build.yaml` to call both workflows at job level via `uses:`, and add `workflow_call` to `build-package.yaml` | Single orchestrating entry point; matches the apparent original intent (build.yaml as the top-level pipeline) | Requires reconciling `build-package.yaml`'s two trigger stories (direct `on: release` vs. `workflow_call` from `build.yaml`) | Satisfies GitHub Actions overlay's reuse guidance directly |
| B. Drop `build.yaml` as an orchestrator; let `build-package.yaml` (on release) and `build-container.yaml` (on workflow_call from wherever it's already invoked) run independently | Less to reconcile | Loses the "one push to main/tag triggers everything" story implied by `build.yaml`'s existence | Simpler, but doesn't match the apparent design intent |

## Decision

Option A. Add `workflow_call` as an additional trigger on `build-package.yaml` (keep
`on: release` too, if standalone release-triggered publishing is still wanted), and rewrite
`build.yaml`'s job to call both reusable workflows at the job level:

```yaml
jobs:
  package:
    uses: ./.github/workflows/build-package.yaml
    secrets: inherit
  container:
    needs: package
    uses: ./.github/workflows/build-container.yaml
    secrets: inherit
```

(Exact `needs`/ordering and input passthrough to be finalized when implemented — this ADR
records the wiring shape, not the final diff.)

## Consequences

- Positive: restores a working push/tag CI pipeline; keeps the two build concerns (package,
  container) as independently testable reusable workflows rather than copy-pasted logic.
- Negative / trade-offs accepted: `build-package.yaml` now has two trigger paths (direct
  release + workflow_call) to reason about.
- Follow-ups: add a workflow-lint or `act`-based smoke test (the repo already has
  `docker/act-build.sh`) so a broken `uses:` path fails fast next time, not silently.
