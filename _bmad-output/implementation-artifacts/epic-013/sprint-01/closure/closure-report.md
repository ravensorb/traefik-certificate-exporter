# E013 / S01 — sprint closure report

Date: 2026-10-09. Session: l3io-pm-20261009T203426Z-8306. Work type: MIXED.

## Stories

| Story | Status | elapsed h | man h | tokens_k |
|---|---|---|---|---|
| E013-S01-001 | done | 0.35 | 8 | 6747.4 |
| E013-S01-002 | done | 0.53 | 12 | 7381.48 |
| E013-S01-003 | done | 0.30 | 14 | 14012.68 |
| E013-S01-004 | blocked (carry-over) | — | — | — |
| E013-S01-005 | done | 0.21 | 10 | 8043.89 |

Velocity 4, carry-over 1.

## Estimate vs actual (sprint)

| Metric | Estimate | Actual (stories + closure) |
|---|---|---|
| elapsed_hours | 10.12–12.88 | 1.67 |
| man_hours | 94.31–133.31 | 40 (re-assessed from the delivered diff before reading the estimate) |
| hitl_hours | 0.98–1.27 | 0 |
| tokens_k | 8870–10080 | 47471.3 (stories 36185.5 + closure 11285.8) |

Calibration: `set-actual` recorded no closure sample. Every metric was skipped as "a child is missing this metric's actual", because E013-S01-004 is blocked and has no actual. Orchestration (§4) was not written by this agent, because it cannot observe the orchestrator's wall-clock. The token residual for the sprint window, from `usage --epic E013 --sprint S01` (100,923.1k) minus the stories and closure, is input 0.392k, output 87.125k, cache_write 1505.225k and cache_read 51859.075k. The orchestrator should verify this residual before recording it.

## Blocked stories

- **E013-S01-004** is blocked by design. The maintainer moved live verification to E013-S02-001 because it needs the maintainer's GitHub/Gitea runners and the `PUBLISH_*` secrets. It is counted as carry-over, not as a closure failure.

## Phases

| Phase | Ran | Output |
|---|---|---|
| Retrospective | yes | `retrospective.md` |
| Clean-release + adversarial (one `bmad-review` pass) | yes | `adversarial-review.md` |
| Red team (`l3io-sec-redteam`) | yes | `redteam-report.md` |
| UX review | **skipped** | No story in the sprint has UX acceptance criteria. The sprint is a CI pipeline change and has no UI. |
| Arch drift (`l3io-arch-review` Mode B) | yes | `arch-drift-review.md`: Blocker 0, Major 3, Minor 7. `check-dispositions` passes. |

## Issues resolved: 11

**Major (2)**
- SD-01-1: the "exempts no path" wording was restated per ADR-0037 in the spine, in ADR-0035 (Carries forward, and an Amended-by pointer to ADR-0037) and in the walkthrough.
- SD-01-2: three `language: pygrep` hooks were added to `.pre-commit-config.yaml`: `gitleaks-no-paths-allowlist`, `workflows-ref-free-checkout` and `workflows-no-act-env`.
  - Each hook was proven by a planted violation, and each one failed: a `paths =` line in `.gitleaks.toml`, a `repository:` checkout in a `.yml` file (testing the file-extension scope), and `env.ACT`.
  - The enforcement text was updated in `.gitleaks.toml`, in the ADR-0033 amendment and in `docs/guidelines.md` §7.

**Medium (3)**
- AR-02: `dist` is now uploaded before any LiquidLogicLabs action runs.
- AR-03: the zizmor `ref-pin` coverage is now stated honestly.
- AR-04: `/poetry.lock` was added to CODEOWNERS.
- The review agent fixed all three.

**Minor/Low (6)**
- SD-01-4: three stale sentences were corrected: the walkthrough's re-run digest, the artifact-action versions in ADR-0035, and the CA-import order in `docs/guidelines.md`.
- AR-11 and AR-12 (the same two walkthrough sentences).
- AR-13: ADR-0035's status line was updated.
- AR-14: ADR-0037 no longer overstates its check.
- RT-E013-08 (the same four sentences). In addition, "fork PRs are safe" is now qualified to GitHub-hosted runners, and ADR-0037's Dependabot claim was corrected.

**Gate after fixes:** `just check` passed: every pre-commit hook passed, and pytest reported 182 passed.

## Issues deferred: 20 (BL-E013-018 … BL-E013-037)

| Severity | Count | Keys |
|---|---|---|
| High | 2 | BL-E013-018 (RT-E013-01: publish secrets have no `environment:`), BL-E013-019 (RT-E013-02 / AR-01 / AR-07: any `v*` tag publishes, and a re-pushed tag splits a version) |
| Medium | 6 | BL-E013-020 (RT-03 / AR-05), -021 (RT-04), -022 (RT-05), -023 (RT-06), -024 (AR-06), -035 (SD-01-3, spec-proposal) |
| Low | 12 | BL-E013-025 … -034 (SD-01-7…10, AR-08/09/10/15, RT-07, RT-09), -036 (SD-01-5, spec-proposal), -037 (SD-01-6, spec-proposal) |

**Why the two HIGH findings were not fixed in closure:** both change recorded design decisions, and both depend on forge-side settings that only the maintainer can apply:
- AD-9 and the secret scoping, which need GitHub environments and a Gitea equivalent;
- AD-12, which needs an ancestor check plus forge tag protection.

Both also need live verification on Gitea and act, which is E013-S02-001's job. They are recorded for the maintainer and architect and should be scheduled into S02 before the first live release.

## Notes

- **Commit deliberately skipped**, per the orchestrator: the index holds stale, partially staged E012 content. Nothing was staged or committed.
- AR-15: a stray empty `uv.lock` is staged in the index. It is outside this sprint's scope and was left as it is (BL-E013-033).
- Stray `dispatch` events from this agent were opened and then closed: agent `closure-x`, session `test`, at 21:00:32Z.
