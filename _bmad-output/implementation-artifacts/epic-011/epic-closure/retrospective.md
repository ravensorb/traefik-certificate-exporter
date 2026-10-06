# Epic 011 — Retrospective

Date: 2026-10-06
Sprints: 1 (sprint-01, the whole epic). Stories: 4 planned, 4 done, 0 carried over, 0 blocked.

This epic ran a single sprint, so this retrospective synthesizes
`sprint-01/closure/retrospective.md` at the epic level rather than aggregating across
multiple sprints — see that file for full detail and per-finding citations.

## Summary

All four planned stories (CI/release evidence, repo governance gates, CLI/settings
hardening, correlation-ID plumbing + atomic certificate writes) landed clean on first pass
(combined 2 fix iterations across 4 stories). Closure then surfaced 56 findings across four
independent reviewers — including 4 HIGH security findings and 2 MAJOR architectural drifts
— and took 2 fix passes to settle. The arch-gate that ran before any code was written caught
4 would-be implementation bugs (AG-1..AG-4) before they shipped, each resolved by a reserved
ADR (0024-0027) and a story patch — the gate paid for itself.

## Velocity vs estimate

| Metric | Estimate (low-high) | Actual | Note |
|---|---|---|---|
| Stories | 4 | 4 done | no carry-over, no blocked |
| `elapsed_hours` | 8.15 (low, sprint) | 3.40 | stories + closure both ran well under |
| `man_hours` (counterfactual) | 35.37 - 39.14 | 42 | re-assessed from the delivered diff before reading this estimate (per step-06 §1); above the high band — see learning 1 below |
| `hitl_hours` | 0.9 - 1.05 | 0.30 | headless run |
| `tokens_k` | N/A | N/A | `runtime: other`, tokens not observable this session |

## Top 3 learnings to carry forward

1. **A story that writes files must also be asked "where does this path come from, and what
   ACL does the written file end up with?"** RT-001/002/003 (path-traversal write, 0644
   private keys/`.pfx`, `dictConfig` RCE via unvalidated config) were all variations of the
   same omission: the sprint hardened the write primitive's atomicity and never audited its
   inputs or resulting permissions. This is why the counterfactual `man_hours` landed above
   the estimate's high band — real security-hardening work the original story scope did not
   anticipate.
2. **A lifecycle/shutdown story must be tested through a real process and a real signal, not
   a direct method call.** Story 4's shutdown design was built and tested for
   `KeyboardInterrupt` only; the shipped container stops on SIGTERM, which bypassed it
   entirely until 3 independent reviewers caught it. Calling a handler directly proves the
   handler, not the deployment.
3. **Run the independent fix-verifier after every fix pass, not only the last one.** Fix pass
   1 introduced its own regression (an uncaught traceback during `runAtStart`, caused by
   installing a SIGTERM handler without updating every `KeyboardInterrupt` catch site to
   match) — caught only because the verifier ran again, not because either fix pass's own
   green suite noticed.

## Carry-over

0 stories. 30 findings deferred to the issues file as `BL-E011-011`...`BL-E011-040` (1 High,
11 Medium, 18 Low) — see `closure-report.md` for the severity breakdown.
