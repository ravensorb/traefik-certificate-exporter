# E014 sprint 02 — retrospective

Written inline by the sprint-closure agent (session l3io-pm-20261011T161302Z-43c8ef). The
`bmad-retrospective` skill is installed, but it reviews a completed epic, and E014 is still
open, so it was not spawned for a single sprint.

## Stories

| Story | Status | Fix iterations | Est. elapsed h | Actual elapsed h | Actual man-h | tests_passing |
|---|---|---|---|---|---|---|
| E014-S02-001 Supply chain | done | 1 | 0.39 | 0.87 | 12 | true |
| E014-S02-002 Destination gating | done | 1 | 0.39 | 2.10 | 10 | true |
| E014-S02-003 Decision-record repair | done | 1 | 0.39 | 0.42 | 11 | **false** |
| E014-S02-004 Close E012, triage backlog | done | 1 | 0.79 | 0.23 | 3 | **false** |
| E014-S02-005 Release 0.3.0 (agent part) | done | 1 | 0.39 | 1.35 | 14 | **false** |
| E014-S02-006 Workflow guards | done | 1 | 0.39 | 0.55 | 8 | **false** |
| E014-S02-007 Release 0.3.0 (maintainer, HITL) | ready-for-dev | — | 0.39 | — | — | — |

Velocity: 6 of 7 stories done. Carry-over: 1 (E014-S02-007).

## `tests_passing: false` — what each one actually is

None of these is a product test failure. Each is the last recorded run of one command, as
`pm-status` records it; the exit codes below are the recorded ones.

- **E014-S02-003, E014-S02-004** — `pm-status audit-issues` exits 4 on 15 legacy E001–E008
  backlog items that predate the current issue schema (BL-E014-070). Pre-existing, outside
  both stories' scope.
- **E014-S02-005** — Verification row 5's host-side seed check exits 1 against a correct image:
  the init script chowns `/config` to `abc` with mode 0700, so the host user cannot read it.
  This is a defect in the story text (BL-E014-076), not the image.
- **E014-S02-006** — Row 9 was recorded as a wrapper command (`grep … | grep -F …`) that exits
  1 on the correct tree. The recorded command itself is broken; the guard it meant to show is
  covered by the `workflows-major-tag-gated` hook, which passes in `just check`.

## What went well

- Supply-chain hardening landed in full: SHA-frozen hook revs, a hash-checked Poetry bootstrap,
  dist hash hand-off between jobs, and a pygrep guard for each rule with its coverage limit
  stated.
- The release dry run under act found a real release blocker, BL-E014-075 (the image version
  label read `0.3` for 0.3.0), before any tag was pushed. It was fixed in this closure and
  proven by a second dry run.
- Closure reviewers found no Critical or High issues across the adversarial, red-team, UX and
  architecture-drift passes.

## What did not go well

- **Evidence that cannot pass.** Four of six done stories recorded a command whose last run is
  non-zero, by design or by a defect in the story text. The same pattern was raised in
  sprint 01. `tests_passing` currently cannot tell "expected failure, verified" from "broken",
  so the signal is noise.
- **Elapsed-time estimates were flat.** Five stories carried the same 0.39 h estimate and
  actuals ranged from 0.23 h to 2.10 h. S02-002 and S02-005 ran several act dry runs against a
  throwaway forge, which a flat per-story band does not model.
- **The first BL-E014-075 guard broke an adopted rule.** The closure's first guard was a pytest
  that parsed workflow files, which CI AD-4 forbids. Arch-drift review caught it as a BLOCKER
  (SD-02-1), and it was replaced by a pygrep hook. The rule was in the spine; it was not
  checked before the guard was written.

## Action items

1. **pm-status: an expected-failure mode for `add-test-run`.** Something like
   `--expect-exit N`, so a negative-control or known-pre-existing failure is recorded as
   verified rather than flipping `tests_passing`. Carried from sprint 01, and still the
   highest-value fix to evidence quality.
2. **Story authoring: run each verification row against the tree before the story is
   committed.** This would have caught S02-005 row 5 and S02-006 row 9.
3. **Estimation: add an "act/forge dry-run" factor** for stories whose verification runs
   workflows end to end.
4. **Before writing a guard, check the spine's AD-4 for the allowed mechanism** (standard
   tool configuration or pre-commit pygrep, never repository code).
5. **E014-S02-007 (maintainer release)** depends on E013-S02-001, still in progress. It
   should tag 0.3.0 only from a tree that contains the BL-E014-075 fix.
