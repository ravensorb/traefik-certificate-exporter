# E014 sprint 01 — closure report (2026-10-11)

## Stories

10 of 10 done (E014-S01-001 … E014-S01-010); carry-over 0; no blocked stories.

## Estimates vs actuals (sprint node)

| Metric | Estimate | Actual (stories + closure) | Notes |
|---|---|---|---|
| elapsed_hours | 9.88–12.58 | 3.62 (3.12 stories + 0.50 closure) | Closure: 19:28–19:48Z and 21:57–22:05Z; the idle wait for the orchestrator in between is excluded |
| man_hours | 146.07–206.47 | 78 | Sprint-level counterfactual, assessed from the diff before reading the estimate. Story actuals sum to 95, so the calibration sample skipped man_hours with "negative residual". |
| hitl_hours | 0.66–0.86 | 0.1 | Maintainer decisions on BL-E014-017 and SD-01-1 layering (`epic-014/execution-notes.md`); assessed, not timed |
| tokens_k | 79,728–90,600 | 93,750.9 (input 1.786, output 117.467, cache_write 3,511.044, cache_read 90,120.595) | Closure share comes from `pm-status usage` over the closure agent and its 6 subagent transcripts, scoped `--since 2026-10-11T19:28:00Z` |

Orchestration block: 2.25 h elapsed, 0 man-hours, 0 HITL hours, tokens_k of 12,755.2 (orchestrator transcript scoped from 16:13:02Z). The calibration sample skipped hitl_hours because the children's total is zero.

## Phases

Every phase ran. The UX review was done inline because the `bmad-ux` Reviewer Gate is GUI-only:
retrospective, clean-release + adversarial (one `bmad-review` pass), red team, UX, sprint architectural drift, and issue triage.

## Issues resolved (8)

| Severity | Count | IDs |
|---|---|---|
| MAJOR | 2 | SD-01-1 (import cycles; import-linter hook added), SD-01-2 (deferred restart re-checks running) |
| MEDIUM | 5 | ADV-1, ADV-2, ADV-3, ADV-4 (fix iteration 1), RT-3 (compose socket warning plus glob-scoped guard test) |
| LOW | 1 | RT-6 (resolved by the ADV-3 fix) |

Fix iterations used: 1 of 3. `check-dispositions` passes with `Blocker: 0, Major: 2, Minor: 7`.
`just check` on the final tree exits 0 with 461 passed and 5 skipped.

Also resolved during closure, by maintainer decision: BL-E014-017 (wontfix; env overrides the config file for all settings; E014-S02-003 documents it).

## Issues deferred (34): BL-E014-027 … BL-E014-060

| Severity | Count | Sources |
|---|---|---|
| Medium | 8 | UX-1 to UX-6, RT-1, RT-2 |
| Low | 26 | ADV-5 to ADV-10, CR-1 merged with SD-01-4, CR-2, SD-01-3 and SD-01-5 to SD-01-9, UX-7 to UX-14, RT-4, RT-5, RT-7, RT-8 |

RT-9 was not re-filed because it duplicates BL-E014-016.

## Evidence-quality items

- E014-S01-008 `tests_passing` is false by derivation. Its fail-first run is recorded under the label `(fail-first, pre-change code)` with exit 1. No green run was recorded under that label, because the label denotes the pre-change code and that run genuinely fails. The same suite on current code is green under the plain command string and in the final `just check`.
- E014-S01-004 and E014-S01-009 recorded expected-failure probes with a synthetic exit 0, so `test_runs` does not show what was executed. Action: give pm-status an expected-failure recording mode. Until then, keep fail-first and probe runs in notes only.
- The closure fix agent wrote a resolution note into the arch-drift Severity cell, which broke `check-dispositions`. Closure restored the cell and recorded the disposition with `spec-align disposition`.
