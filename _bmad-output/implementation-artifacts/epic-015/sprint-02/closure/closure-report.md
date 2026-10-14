# E015 sprint 02 — closure report

Date: 2026-10-14. Work type MIXED, no skipped phases. Runtime `other`: no session transcript, so the token actuals of this closure and of S02-002 are N/A.

## Stories

| Story | Status | Elapsed h | Man h | HITL h | Tokens k |
|---|---|---|---|---|---|
| E015-S02-001 buildx `buildkitd-config` + guard | done | 2.10 | 12 | 0.25 | 41,595.0 |
| E015-S02-002 publishing tokens (MD-26) | done | 0.75 | 10 | 1.00 | N/A |
| E015-S02-003 hook deps from `poetry.lock` | done | 0.30 | 7 | 0 | 6,016.6 |
| E015-S02-005 `settings.loaddotenv` | done | 0.65 | 12 | 0 | 18,318.8 |
| E015-S02-004 release 0.3.1 | ready-for-dev, carried over | — | — | — | — |

Carry-over: 1 (S02-004, the maintainer's release, as with E014-S02-007). Blocked stories: none.

**S02-002's actual was written at closure.** Its story agent ended at the block and the maintainer closed the block later, so no actual had been recorded. Elapsed is the story dispatch (10:42–11:22Z) plus the 13:40Z environment setup. HITL of 1.0 h is assessed, not observed; it covers the maintainer's MD-26 decision during the 2.4 h block window, which is its upper bound. Tokens are N/A.

**`tests_passing` quirks:** S02-002 is false only because retired row 9 (the 0.3.0 `onedigest` check) keeps its exit 1. S02-001 is false only because superseded commands keep an old exit 1. Live rows pass in both. No runs were invented to change the flag.

**Sprint estimate vs actual.** The man-hours were formed at 32 from the delivered diff before the estimate was read. The estimate was 78–110, but it includes S02-004 and the release work. Elapsed: 5.0–6.2 h estimated, 4.0 h actual (stories 3.8 plus closure 0.2). Tokens: 62.0–70.5 M estimated; the sprint actual is N/A. The three stories with observed tokens total 65.9 M, and S02-002 and closure are unobserved.

## Orchestrator items

1. **Sprint marked `done` with S02-004 open.** `set-status` accepted it, the same way E014 S02 closed with E014-S02-007 carried over. S02-004 stays `ready-for-dev`.
2. **No closure calibration sample.** Every metric was skipped with "a child is missing this metric's actual", because S02-004 has none. The node therefore has no `calibration_sampled_at` marker, so a `set-actual` re-run after S02-004 is done would sample normally.
3. **Orchestration block not written.** This subagent cannot see the orchestrator's own spend, and a second call on the node records nothing. The orchestrator should write `--block orchestration` itself.
4. **MD-26 kept as the target.** No reviewer finding restores MD-10 … MD-15. The one design fix (AR-1) narrows the GHCR fallback to github.com, which is what ADR-0052 and AD-13 already said.
5. **Maintainer decision (optional):** RT-2 / BL-E015-065. A raw `act` run of `release.yaml` outside `just act` can create a real GitHub release with the `gh auth token`. MD-26 dropped the workstation rule on purpose, and a one-expression guard (`github.actor != 'nektos/act'`) is available if wanted.

## Phases

| Phase | Ran | Output | Result |
|---|---|---|---|
| Retrospective | yes (inline) | retrospective.md | 4 action items |
| Clean-release + adversarial (one pass) | yes (inline; this runtime has no subagent tool) | adversarial-review.md | 0 HIGH, 1 MEDIUM, 2 LOW; all fixed |
| Red team | yes (inline) | redteam-report.md | 3 LOW, deferred |
| UX review (S02-002, S02-005) | yes (inline) | ux-review.md | 2 LOW, deferred |
| Arch drift (Mode B, spec alignment on) | yes (inline) | arch-drift-review.md | Blocker 0, Major 1, Minor 3; `check-dispositions` OK |
| Fix loop | 1 iteration, in place | — | the MEDIUM and MAJOR fixed |

Gate on the final tree: `just check` exit 0, with every pre-commit hook passing and pytest at `629 passed, 16 skipped` (the skips are the opt-in Docker integration tests).

## Issues resolved (4)

| Severity | Items |
|---|---|
| Medium | AR-1 = SD-02-1: the GHCR job-token fallback is now limited to `github.server_url == 'https://github.com'` in `dev.yaml` and `release.yaml` (six expressions); walkthrough, spine AD-9 example, ADR-0052 bullet and spine changelog updated |
| Low | AR-2 = SD-02-4 (`docs/upgrading.md` mirrored-run wording), AR-3 (`justfile` raw-`act` comment), SD-02-3 (spine sources line names MD-26) |

## Issues deferred (5, all Low)

| Key | Source | Item |
|---|---|---|
| BL-E015-063 | RT-3 / SD-02-2 | Replace `PUBLISH_GITEA_TOKEN` (general Infisical `GITEA_TOKEN`, shared with E2E/TEST) with a `write:package`-only token |
| BL-E015-064 | RT-1 | Write-scoped job tokens reachable by major-tag LiquidLogicLabs actions (accepted residual of MD-26 goal 2) |
| BL-E015-065 | RT-2 | Raw `act` run can create a GitHub release with the `gh` token |
| BL-E015-066 | UX-1 | "Not reading .env" WARNING repeats with no hint how to clear it |
| BL-E015-067 | UX-2 | `--no-dotenv` help says the image "sets this" (it sets the env var) |

## Not staged

`_bmad/scripts/pm-status.py` (a 2-line maintainer module bump) and `_bmad/memory/`, as at S01 closure.
