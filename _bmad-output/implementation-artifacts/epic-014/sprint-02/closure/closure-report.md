# E014 sprint 02 — closure report

Session l3io-pm-20261011T161302Z-43c8ef, 2026-10-11. Work type MIXED; `skip_phases` is
empty, so every phase ran.

## Stories

Six of seven stories are done. E014-S02-007 (the maintainer-run release, HITL) is
`ready-for-dev` and is the one carry-over. It also depends on E013-S02-001, which is still in
progress. No story is `blocked`.

| | Estimate | Actual |
|---|---|---|
| man_hours | 91.26–128.99 | 52 (sprint-level counterfactual, assessed from the diff before the estimate was read; the six stories' own man-hours sum to 58) |
| elapsed_hours | 4.44–5.61 | 5.52 for the stories, plus closure (see sprint `actual`) |
| hitl_hours | 0.25–0.31 | 0 |
| tokens_k | 47,732–54,241 | 73,535.6 for the stories, plus closure (see sprint `actual`) |

### `tests_passing: false` on four done stories

These are recorded as they are, not corrected. Details are in `retrospective.md`.

- **E014-S02-003 and S02-004:** `audit-issues` exits 4 on 15 legacy E001–E008 items. This was already the case before the sprint (BL-E014-070).
- **E014-S02-005:** the row-5 seed check exits 1 on a correct image, because the story text is wrong (BL-E014-076).
- **E014-S02-006:** the recorded row-9 wrapper command exits 1 on the correct tree. The command itself is broken.

## Release blocker fixed in this closure: BL-E014-075 (High)

- **Fix.** The image-version `type=raw` tag line in `release.yaml` and `dev.yaml` now carries `priority=1000`.
- **Cause.** The metadata action takes `org.opencontainers.image.version` from the highest-priority tag. `type=semver` (900) outranks `type=raw` (200), so the label came out as the wrong value.
- **Guard.** The new `workflows-version-label-priority` pygrep hook enforces the fix. A planted removal makes it exit 1. Its coverage limit is stated in `.pre-commit-config.yaml` and in CI AD-8.
- **Proof.** An act release dry run in a throwaway clone with a local `registry:2` exited 0:
  - the label is `0.3.0` on both amd64 and arm64;
  - the tags are exactly `0.3.0`, `0.3` and `latest`;
  - `:0` returns 404;
  - there are zero `partially configured` warnings.

  The evidence is in `release-0.3.0-evidence.md`, in its "BL-E014-075 fix" section. Nothing was published to a real forge or registry.
- **Resolution recorded.** `resolve-issue --resolution fixed` requires a commit SHA, so the issue is resolved against closure commit 3880faf, in a follow-up commit.

## Phases

| Phase | Ran | Output | Result |
|---|---|---|---|
| Retrospective | yes (inline; `bmad-retrospective` is epic-scoped) | `retrospective.md` | carry_over 1 |
| Clean-release + adversarial (one `bmad-review` pass) | yes | `adversarial-review.md` | Critical 0, High 0, Medium 5, Low 7 |
| Red team (`l3io-sec-redteam`) | yes | `redteam-report.md` | Critical 0, High 0, Medium 3, Low 4, plus 1 observation |
| UX review (`bmad-ux` Reviewer Gate had no DESIGN/EXPERIENCE docs, so the reviewer reviewed directly) | yes | `ux-review.md` | High 0, Medium 4, Low 5 |
| Architectural drift (`l3io-arch-review` Mode B) | yes | `arch-drift-review.md` | Blocker 1, Major 1, Minor 5; `check-dispositions` exit 0 |
| Issue triage | yes | `state/issues.yaml` | see below |

### Arch-drift BLOCKER and MAJOR

- **SD-02-1 (BLOCKER), `resolved-in-code`.** The first guard written for BL-E014-075 was a pytest that parsed the workflow files, which CI AD-4 forbids. It was removed and replaced by the pygrep hook.
- **SD-02-2 (MAJOR), `spec-updated`.** The CI spine's AD-8 tag list now includes `priority=1000`, and the hook is added to the AD-3 hook list. ADR-0046 gains item 14, and an entry was added to the spine's `.memlog.md`.

## Issues

**Resolved in this closure: 6.**

| Severity | Finding | Resolution |
|---|---|---|
| High | BL-E014-075 | fixed, as described above |
| Blocker | SD-02-1 | the pytest guard was removed |
| Major | SD-02-2 | AD-8 amended |
| Low | CR-1 | the AGENTS.md verification marker no longer cites an uncommitted tree |
| Low | AR-7 and RT-7 | both concerned the removed pytest |

AR-4's false claim in ADR-0046 item 1 was also corrected in the text. The unhashed Dockerfile install it pointed at remains open, as BL-E014-079.

**Deferred: 27**, as BL-E014-077 to BL-E014-103.

- **Medium (11):** AR-2, AR-3, AR-4 (the Dockerfile part), AR-5, RT-1, RT-2, RT-3, UX-1, UX-2, UX-3, UX-4.
- **Low (16):** AR-6, AR-8, AR-9, AR-10, AR-11, RT-5, RT-6, SD-02-3, SD-02-4, SD-02-5, SD-02-7, UX-5, UX-6, UX-7, UX-8, UX-9.
- **Not refiled:** AR-1 and RT-8 duplicate the existing BL-E013-022.

The sprint-closure workflow says an adversarial MEDIUM is fixed in place. The five adversarial Mediums were deferred anyway, for these reasons:

| Finding | Why it was deferred |
|---|---|
| AR-1 | Already tracked, as BL-E013-022. |
| AR-2 | Contradicts AD-9, which is ADOPTED ("always exits 0"). Changing it needs a maintainer decision. |
| AR-3 | A change to the release-workflow design that the maintainer should decide before tagging. |
| AR-4 | Its documentation part was fixed. The remaining part needs a Dockerfile change, which needs an image rebuild and re-verification. |
| AR-5 | The suggested pytest is forbidden by AD-4. |

None of the deferred findings is Critical or High.

## Gates

- **`just check`:** exit 0 on the final tree. Pre-commit hooks passed, including the new hook, and pytest reported 462 passed, 5 skipped. `pip-audit-bootstrap` was skipped as "no files to check", because `.github/requirements/poetry.txt` was untracked. After commit 3880faf it was run with `pre-commit run pip-audit-bootstrap --all-files`: it ran (not skipped) and passed, exit 0.

## Sprint status

The sprint's status is left as reported by `pm-status` (see the final status line). E014-S02-007 is open and was not marked done or blocked. Epic closure was not run.
