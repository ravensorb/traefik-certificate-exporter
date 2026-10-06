# Epic 011 / Sprint 01 — Retrospective

Date: 2026-10-06
Sprint: **01 — Residual Backlog Cleanup**
Stories: 4 planned, 4 done, 0 carried over, 0 blocked.

## Summary

Sprint 01 closed all four planned stories and resolved the ten backlog items they were
scoped against, but the value of the sprint was not where the plan put it. The planned work
— CI/release evidence, repo governance gates, CLI and settings hardening, correlation IDs
plus atomic certificate writes — landed clean on the first pass with a combined fix
iteration count of 2 across four stories. Closure then found 56 findings across four
reviewers, including four HIGH security findings and two MAJOR architectural drifts, and
took two fix passes to settle. The sprint's actual cost is roughly evenly split between
building the feature and discovering what building it had assumed.

## Velocity vs estimate

| Metric | Estimate (low–high) | Actual | Note |
|---|---|---|---|
| Stories | 4 | 4 done | no carry-over, no blocked |
| `elapsed_hours` | 5.69 – 7.44 | 3.10 | stories ran well under; closure added 0.55 |
| `man_hours` (counterfactual) | 27.65 – 38.06 | 39.5 | re-assessed from the delivered diff, above the high band |
| `hitl_hours` | 0.65 – 0.87 | 0.30 | headless run |
| `tokens_k` | 678 – 770 | N/A | `runtime: other`, tokens not observable |

The `man_hours` overrun against an `elapsed_hours` underrun is the honest shape of this
sprint: the agents were fast at the planned work and the closure phases then delivered a
second sprint's worth of security hardening that nobody estimated.

## What went well

- **The arch gate paid for itself before a line was written.** Four MAJOR pre-implementation
  findings (AG-1…AG-4) were each resolved by a reserved ADR (0024–0027) and a story patch.
  All four would otherwise have been implementation bugs: the `.pfx` atomicity gap, the
  `globalArgs` `ImportError`, the `None.cancel()` crash, and a story citing prose that did
  not exist in the file it named.
- **The repo's "prove it with an injected fault" rule held.** Every safety property added
  this sprint is backed by a test that breaks something — `os.replace` made to raise, a
  planted untracked file in a throwaway git repo, a planted CODEOWNERS count drift, a real
  SIGTERM into a real subprocess, a 60-iteration timer race. None of the new tests are
  happy-path-only.
- **Story 3's redaction work was verified empirically by an adversary, not just by its own
  tests.** The red team executed against the live venv with planted credentials and found
  all three sinks clean. That is the strongest evidence any story in this epic carries.
- **Zero dependencies added.** Ten write sites collapsed to one helper; `atomicwrites` and
  `deepdiff` were both considered and rejected in favour of stdlib.

## What went badly

- **The sprint formalised trust assumptions without re-examining them.** ADR-0023 and
  ADR-0024 reasoned carefully about *how* certificate bytes are written and never asked
  *where*. The result was RT-001: `domain.main` flowing unvalidated into a filesystem path,
  so the sprint's own new atomic writer became the payload carrier for an arbitrary-file-write
  as root. An existing hazard was hardened around rather than found.
- **"Safe shutdown" was built for a signal the product never receives.** Story 4's entire
  shutdown design — the latch, the bounded drain wait, the observability lines — was
  reachable only from an interactive Ctrl-C, while the shipped container stops on SIGTERM.
  The runbook written in the same sprint claimed SIGTERM was handled. Three independent
  reviewers found this; no story test did, because every test called `cancel()` directly.
- **An ADR amendment asserted a property the code did not enforce.** ADR-0023 Amendment 4a
  claimed the shutdown latch covered all three paths; `doTheWork` checked nothing at entry
  (SD-01-1 / AD-02). Writing the decision and writing the enforcement drifted apart inside
  one story.
- **A story was marked `done` with its own stated closure condition unmet.** BL-E007-002
  required "an actual green run whose result is retained"; the retained evidence is a
  first-step failure that explicitly says a wrapper change — not a rerun — is needed
  (SD-01-2). The residue was narrated in prose instead of being given a tracked id.
- **Fix pass 1 introduced its own regression.** Installing the SIGTERM handler
  unconditionally while only the watch block caught `KeyboardInterrupt` turned a silent
  exit-143 during the `runAtStart` sweep into an uncaught traceback. Caught by the
  independent verifier, not by the fix pass's own green suite.

## What to change

1. **Make "where does this path come from?" a standing question for any story that writes
   files.** The three highest findings this sprint (RT-001, RT-002, RT-003) are all the same
   omission: the sprint owned the write primitive and not its inputs or its resulting ACL.
2. **A shutdown/lifecycle story must be tested through a real process and a real signal.**
   Calling the handler directly proves the handler, not the deployment.
3. **When an ADR amendment asserts an invariant, the same story must land the enforcement
   and a test named after the invariant.** SD-01-1 existed entirely in the gap between those.
4. **A story may not reach `done` while its own quoted closure condition is unmet unless the
   residue carries a backlog id.** Prose in a runbook is not tracking.
5. **Run the independent fix-verifier after every fix pass, not only after the last one.**
   It found the one regression that two green suites missed.

## Carry-over

**0 stories.** All four completed. 30 findings were deferred to the issues file as
`BL-E011-011` … `BL-E011-040` (1 High, 11 Medium, 18 Low) — see `closure-report.md` for the
severity breakdown and the justification for the single deferred HIGH.
