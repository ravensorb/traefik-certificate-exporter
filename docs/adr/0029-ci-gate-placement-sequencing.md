# ADR-0029: Governance gates land in verify-build.yaml; Story 3 lands before Story 2

- **Status:** Superseded by ADR-0035
- **Date:** 2026-10-08
- **Deciders:** Maintainer + architecture gate (l3io-arch-review, bmad-agent-architect)
- **Epic:** E012
- **Departs from spec:** n/a
- **Principle(s) in tension:** CI-AR5 (stable topology), CI-AR45 (ci.yaml collapses to a
  single `verify-build.yaml` call), ADR-0028 (ref-free checkout)

## Context

Epic E012, Sprint 01 has two stories landing in the same sprint that both touch the CI/CD
workflow files:

- **Story E012-S01-002** (CI & supply-chain integrity) adds three new gates — an
  action-SHA-pin check, a directory-scoped untracked-file check, and a `vendored-trees.lock`
  -backed vendored-integrity check. Its technical AC, as elaborated, named
  `ci.yaml`/`dev.yaml`/`release.yaml` as the landing site, with the exact location marked
  `N/A — exact gate script location not yet confirmed`.
- **Story E012-S01-003** (ref-free checkout, ADR-0028/CI-AR42–CI-AR46) collapses `ci.yaml`
  (and `dev.yaml`/`release.yaml`) from a `plan` + `verify` job pair down to a single job that
  calls reusable `verify-build.yaml`, and changes `verify-build.yaml`'s own input contract
  (drops `source-sha` as a required input, makes `package-version` optional).

The architecture gate (two independent reviewers, both MAJOR, confirmed) flagged that Story
2's placement assumption is built on the pre-refactor three-channel-file job shape that
Story 3 deletes in the same sprint, and that neither story document sequences or reconciles
the two edits to the same files. Landing Story 2's gates against the current file shape risks
placing them in jobs Story 3 removes before the sprint closes.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Land Story 2's gates in `ci.yaml`/`dev.yaml`/`release.yaml` as originally drafted, implement Story 2 first | No change to Story 2's draft AC | Gates get deleted or silently orphaned when Story 3 collapses these files to a single `verify-build.yaml` call later in the same sprint | Violates CI-AR5 (stable topology) the moment Story 3 lands |
| B. Land Story 2's gates in `verify-build.yaml`, sequence Story 3 before Story 2 | `verify-build.yaml` already hosts channel-agnostic governance-style jobs (`gitleaks`, `actionlint`, `file-hygiene`, `source-integrity`) — the three new gates are the same shape; gates run once per build instead of duplicated per channel caller; no rework needed once Story 3 lands | Requires explicit sprint-level sequencing (not previously declared) | Matches CI-AR3 (action-first composition / repo Python owns only project-specific validation), CI-AR5, and ADR-0028's reusable-file topology |
| C. Land gates in both the collapsed `ci.yaml`-family callers and `verify-build.yaml` (duplicate) | Avoids a hard sequencing dependency | Duplicate enforcement of the same checks, contradicts CI-AR5's partition intent, doubles maintenance | Rejected — no standards benefit, real cost |

## Decision

**Option B.** Story E012-S01-002's three new gates (action-SHA-pin, untracked-file,
vendored-integrity) land as new jobs/steps in `verify-build.yaml`, alongside its existing
governance-style jobs (`gitleaks`, `actionlint`, `file-hygiene`, `source-integrity`) — not in
`ci.yaml`/`dev.yaml`/`release.yaml`. These are channel-agnostic static/supply-chain checks;
`verify-build.yaml` is the single reusable file every channel caller already invokes once
Story 3 lands, so placing them there runs each gate exactly once per build regardless of
channel, consistent with CI-AR5's five-file partition.

Sprint sequencing: **Story E012-S01-003 is implemented and merged before Story
E012-S01-002's gate-placement work begins.** Story 2's technical AC is patched (see below) to
target the post-CI-AR45 `verify-build.yaml` shape directly, removing the
`N/A — not yet confirmed` placeholder.

## Consequences

- Positive: gates run once per build, not once per channel file; no rework when Story 3's
  collapse lands; resolves the architecture gate's confirmed MAJOR finding without
  introducing a new workflow-file structure.
- Negative / trade-offs accepted: Story 2 cannot start its CI-file edits until Story 3 is
  merged — a sprint-level ordering constraint that did not previously exist, accepted as
  the smaller cost against rework or duplicate gates.
- Follow-ups: none — both stories' docs are patched directly as part of this ADR's
  resolution; no further decision is deferred.
