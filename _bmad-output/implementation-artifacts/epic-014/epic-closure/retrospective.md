---
epic: E014
date: 2026-10-12
verdict: accepted-with-open-items
criteria: profiled
headless: true
---

# Epic retrospective: E014 (0.3.0 release readiness)

## Retrospective summary

E014 delivered all 17 stories across two sprints and shipped 0.3.0 to PyPI, Docker Hub (`0.3.0`/`0.3`/`latest`) and Gitea, from GitHub release run 38281339396 and a local-act Gitea publish. A live-host test against production ACME data then produced the same certificates as 0.2.0. The recurring weakness was evidence quality, not product quality. Five done stories carry `tests_passing: false` because of how runs are recorded, flat estimates did not tell stories apart, and the sprint-01 action item that would fix the recording (an expected-failure mode in pm-status) was still open at epic end. The epic is accepted with open items: BL-E014-105/106/107/108 move to E015 "0.3.1", and E013's epic closure is still to run.

## Learnings

- Keep `tests_passing` meaningful: pm-status needs an expected-failure mode, because fail-first and probe runs made 5 of 17 done stories read as failing.
- Run every story verification row against the tree before committing the story, because broken rows (S02-005 row 5, S02-006 row 9) became permanent red evidence.
- Check the spine's adopted mechanisms (CI AD-4) before writing a guard. The first BL-E014-075 guard was a forbidden pytest and was caught as a BLOCKER.
- End-to-end dry runs (act against throwaway registries) and a live-host parallel test found defects that unit gates could not: BL-E014-075 before tagging, BL-E014-105/106/107 after.
- Flat per-story estimates hid real variance (0.27x to 5.4x on elapsed). ADR-bearing and act/forge dry-run stories need their own weighting.

## Epic summary

- **Epic:** E014, "0.3.0 release readiness". Goal (`state/active/epic-014/epic.yaml`): "Ship 0.3.0: make restart, PKCS12, ACME parsing and settings actually work; harden the CI supply chain and destination gating; repair the decision record; close E012; release 0.3.0 from protected tags."
- **Range:** sprint 01 closed at `6e230db`; sprint 02 closed at `3880faf` and `e410285` (BL-E014-075 resolution). Post-closure commits: `c7394e2` (AR-3: `latest` moves only for the highest release tag, BL-E014-078 fixed), `e55dca7` and `9f05d19` (Gitea live publish and live-host test evidence), `046016b` (BL-E014-106 raised from Low to Medium for 0.3.1 scope; also the commit `v0.3.0` was tagged on, per `notes-E014-S02-007.md` AC 6).
- **Stories:** 17 of 17 `status: done` (pm-status: S01 10/10 done, S02 7/7 done). E014-S02-007 (maintainer release) was carried over at sprint-02 closure (`sprint-02/closure/closure-report.md` "Stories") and closed afterwards. Its `done` state and `notes-E014-S02-007.md` are still uncommitted in the working tree (`git status`), so the commit message "close sprint S02 — 6 stories" is correct for its time.
- **Release outcome** (`notes-E014-S02-007.md` AC 6–8, `gitea-live-publish-2026-10-12.md`): run 38281339396 `success` with 2 `enabled` lines (PyPI, Docker Hub) and 0 `partially configured`. PyPI 0.3.0 wheel and sdist hashes match the run outputs. Docker Hub `0.3.0`/`0.3`/`latest` share one digest, amd64 and arm64, label `0.3.0`, no `:0`. Gitea package and image 0.3.0 were published from local act on `c7394e2`, so the Gitea image digest differs from Docker Hub's by construction.
- **Evidence inventory.**
  - Read: both sprint retrospectives and closure reports; `release-0.3.0-evidence.md`, `gitea-live-publish-2026-10-12.md`, `live-host-test-rwusdckrls6-2026-10-12.md`, `local-release-test-2026-10-12.md` (via commit `c7394e2`'s message); `notes-E014-S02-007.md`; `pm-status show --epic E014`; per-story state nodes (status, `tests_passing`, `fix_iterations`); E014 entries in `state/issues.yaml` and `issues-resolved.yaml`; the `git log` above.
  - Missing or not used: `sprint-status.yaml` (this project uses sharded l3io-pm state, so the skill's `detect-epic` and `update` could not run); no epic-level diff review; no session logs; no previous epic retrospective (E013 has none).

## Velocity

Epic-level, from `pm-status show --epic E014` against the `epic.yaml` estimate:

| Metric | Estimate | Actual (TOTAL) | Of which stories |
|---|---|---|---|
| elapsed_hours | 19.86–24.37 | 12.39 | 9.64 |
| man_hours | 305.76–334.8 | 156 | 156 |
| hitl_hours | 1.23–1.43 | 0.6 | 0.5 |
| tokens_k | 149,766–170,188 | 223,867.43 | 145,663.9 |
| cost ($) | 116.65–132.54 | 180.71 | 114.35 |

- Elapsed time, man-hours and HITL came in under estimate. Tokens and cost came in over, by about 1.3–1.5x, and the overrun sits in closure (39,594 k) and orchestration (38,610 k), not in the stories (145,664 k is inside the band).
- Per story, flat estimates hid the spread. In S01 every story was estimated at 0.75 h, and actual elapsed ran 0.27x–0.67x; tokens ran 0.54x–1.96x, with S01-006 (the ADR-0045 cooldown story) at the top (`sprint-01/closure/retrospective.md` §2). In S02, five stories were estimated at 0.39 h and actuals ran 0.23–2.10 h. S02-002 ran 2.10 h against 0.39 h, about 5.4x, driven by act dry runs against a throwaway forge (`sprint-02/closure/retrospective.md`).
- Rework was low. 15 stories recorded `fix_iterations: 1`, and S01-008 and S02-007 recorded 0. Neither sprint needed a second review cycle. Sprint closures each used 1 of 3 fix iterations.

## Findings

Every finding is tied to its source. The disposition is given as *instance / prevention*.

### Recurring across both sprints

| # | Finding | Source | Disposition |
|---|---|---|---|
| F1 | `tests_passing: false` on 5 done stories, none of them a product failure. **E014-S01-008:** its fail-first run is labelled `(fail-first, pre-change code)` with exit 1 and has no later run under that label. **E014-S02-003, E014-S02-004:** `pm-status audit-issues` exits 4 on 15 legacy E001–E008 items (pre-existing, BL-E014-070). **E014-S02-005:** the row-5 host-side seed check exits 1 on a correct image (BL-E014-076, a story-text defect). **E014-S02-006:** the row-9 wrapper command exits 1 on the correct tree (the guard it targets passes in `just check`). | state nodes; `sprint-01/closure/closure-report.md` "Evidence-quality items"; `sprint-02/closure/closure-report.md` "`tests_passing: false`" | Accept as recorded (no green run invented) / tooling fix, A1 |
| F2 | Synthetic exit codes: S01-004 and S01-009 recorded expected-failure probes with `exit_code: 0`, so `test_runs` does not show what actually ran. | `sprint-01/closure/retrospective.md` §5.2 | Accept for history / A1, A2 |
| F3 | The sprint-01 action item A1 (expected-failure mode in pm-status) was carried into sprint 02 and was still open at epic end. Sprint 02 then added four more false flags. | `sprint-02/closure/retrospective.md` action 1 | Escalate / A1 |
| F4 | Flat estimates: one band per story in both sprints, against actual spreads of 0.27x–0.67x (S01 elapsed) and 0.23–2.10 h (S02). S01 action A7 did not reach the S02 plan. | both sprint retrospectives | Defer / A4 |
| F5 | Prose overstating coverage was the most common S01 review finding (S01-005 F1, S01-007 F1, S01-009 M3). In S02, ADR-0046 item 1 (AR-4) made a false claim that was corrected in the text, and the Dockerfile part stays open as BL-E014-079. | `sprint-01/closure/retrospective.md` §4; `sprint-02/closure/closure-report.md` "Issues" | Fixed or filed / global rule 3 already covers it; keep in review lenses |
| F6 | Verification rows were wrong in the story text (S02-005 row 5, S02-006 row 9), and the error surfaced only at execution as permanent red evidence. | `sprint-02/closure/retrospective.md` | Filed (BL-E014-076) / A3 |

### Sprint 02 and release

| # | Finding | Source | Disposition |
|---|---|---|---|
| F7 | Release blocker BL-E014-075: the image version label read `0.3` for 0.3.0. The act dry run found it before any tag, and it was fixed with `priority=1000` plus the `workflows-version-label-priority` hook. | `release-0.3.0-evidence.md` "BL-E014-075 fix" | Fixed (`3880faf`) |
| F8 | The first BL-E014-075 guard was a pytest that parsed workflow files, which CI AD-4 forbids. Caught as SD-02-1 BLOCKER and replaced by a pygrep hook. | `sprint-02/closure/closure-report.md` "Arch-drift BLOCKER and MAJOR" | Fixed / A5 |
| F9 | AR-3, `latest` moving backwards on older or re-run tags (BL-E014-078), was deferred at closure and fixed before release. The release log shows `is-latest=true`. | commit `c7394e2`; `issues-resolved.yaml`; `notes-E014-S02-007.md` AC 6 | Fixed |
| F10 | The release reached a subset of destinations by maintainer choice. Not configured: GHCR, Gitea-from-GitHub and the forge release (`gh release view v0.3.0` → not found). The `release-tags` ruleset, F-02 and secret scanning were not re-queried. The epic goal says "from protected tags", but that is not re-evidenced at release time. | `notes-E014-S02-007.md` AC 2, 4, 9 | Accept (maintainer choice) / open item |
| F11 | Production on rwusdckrls6 runs `ghcr.io/…:latest` under Watchtower, and GHCR is not a configured destination, so production does not pick up 0.3.0 automatically. | `live-host-test-rwusdckrls6-2026-10-12.md` "Note for the release" | Open item (A7) |
| F12 | Gitea publishing used the maintainer's admin token. ADR-0039 recommends a scoped bot account. | `gitea-live-publish-2026-10-12.md` "Notes" | Defer / open item |

### Found by the live-host test (carried to E015 "0.3.1", maintainer decision)

| # | Issue | Severity | Source |
|---|---|---|---|
| F13 | BL-E014-105: watch mode misses a store replaced by atomic rename (no `on_moved`). Traefik writes in place, so production is unaffected. | Medium | live-host test D |
| F14 | BL-E014-106: about 1–1.5 s per certificate per pass. Raised from Low to Medium in `046016b`. | Medium | live-host test "Timing" |
| F15 | BL-E014-107: legacy detection misses pre-confuse env names. Production sets `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME=1` and gets no warning. | Low | live-host test A |
| F16 | BL-E014-108: setup-buildx v4 ignores the `config` input (renamed `buildkitd-config`), so the private-CA BuildKit config is never applied. | Medium | release run 38281339396 log; `notes-E014-S02-007.md` AC 6 |

### Backlog at epic end

- 98 E014 items remain in `state/issues.yaml` `backlog` (22 Medium, 76 Low); 10 E014 items are in `issues-resolved.yaml`.
- None of the deferred items is Critical or High (both closure reports).

### Scope narrowing (recorded)

- No `bmad-review` pass ran over the whole epic diff. Each story was code-reviewed, and each sprint closure ran adversarial, red-team, UX and arch-drift reviews, so the cross-story review exists only per sprint.
- The cross-sprint boundary (S01 product code under S02 workflow changes) was not reviewed as one diff. The live-host test is the only end-to-end evidence that spans both.

## Behavior verification

This retrospective exercised nothing itself. Recorded runtime evidence:

- **Live-host parallel test on rwusdckrls6 with production ACME data, image `0.3.0`** (`live-host-test-rwusdckrls6-2026-10-12.md`).
  - Run-once exported 67 certificates, with SHA-256 fingerprints identical to production 0.2.0.
  - PKCS12 with a passphrase works (leaf plus 2 intermediates).
  - An unchanged second pass changes nothing.
  - Watch mode extracts only the changed domain and runs the hook once.
  - A labelled container restarts, and the cooldown defers rather than drops.
  - Failed: an atomic-rename replacement (BL-E014-105).
- **Published artifacts** (`notes-E014-S02-007.md` rows 13 and 16): PyPI 0.3.0 installs and runs `--help` on Python 3.10 and 3.14; the Docker Hub `0.3.0` smoke run exits 0.
- **Gitea** (`gitea-live-publish-2026-10-12.md`): `--help` exits 0 on `:0.3.0` for amd64 and arm64.
- **Gates:** `just check` 462 passed, 5 skipped on `046016b` (maintainer-run, AC 1).

## Previous-retro follow-through

- There is no previous epic retrospective: E013 has no epic closure or retrospective. There is no `sprint-status.yaml` and no `action_items` list, so there is nothing to change with `--set-action-status`.
- The sprint-01 retrospective's action items, checked against the sprint-02 evidence:

| S01 item | Landed? | Evidence |
|---|---|---|
| A1 expected-failure mode in pm-status | No | `sprint-02/closure/retrospective.md` action 1, "Carried from sprint 01" |
| A2 no synthetic exit codes | Yes, in S02 | S02 records real exit codes, which is why four of its flags are red (`sprint-02/closure/retrospective.md`) |
| A3 decide BL-E014-017 | Yes | resolved wontfix by the maintainer on 2026-10-11 (`sprint-01/closure/retrospective.md` "Closure review outcome") |
| A4 reword the 0.3.0 `watchforchanges` release note | Not checked | not checked by this retrospective |
| A5 notes written before review, A6 ruff before `just check` | No evidence found | not reported in S02 either way |
| A7 per-story estimates | No | S02 used a flat 0.39 h band (F4) |
| A8 move `sprint.yaml` out of `backlog` at closure | No evidence found | not checked |

## Action items

All items are proposed only. Nothing was applied, and no state was changed.

| # | Action | Owner (proposed) | Source |
|---|---|---|---|
| A1 | Add an expected-failure recording mode to `pm-status add-test-run` (for example `--expect-exit N`): store the real exit code and the expectation, and keep it out of the `tests_passing` derivation. This is the third carry and needs escalation, not another restatement. | l3io-pm tooling maintainer | F1, F2, F3 |
| A2 | Until A1 ships, record fail-first and probe runs in notes, or as the real outer exit of a capturing command line. | Story agents | F1, F2 |
| A3 | Story authoring: run each verification row against the tree before the story is committed. | l3io-plan / story authors | F6 |
| A4 | Estimate per story, with factors for ADR-bearing, container-test and act/forge dry-run work. | l3io-plan (estimate) | F4 |
| A5 | Before writing a guard, check the spine's AD-4 for the allowed mechanism. | Story and closure agents | F8 |
| A6 | Plan E015 "0.3.1" with BL-E014-105, 106, 107 and 108. | Maintainer / l3io-plan | F13–F16 |
| A7 | Decide how production on rwusdckrls6 gets 0.3.0: configure GHCR as a destination, or repoint the production image. | Maintainer | F11 |
| A8 | Run E013's epic closure, since all its stories are done. | Maintainer / l3io-execute | task brief; `active/epic-013/epic.yaml` `status: in-progress` |
| A9 | Run E014's epic closure in state and commit the uncommitted E014-S02-007 closure (state node, story file, notes). | Epic-closure agent | `git status`; `active/epic-014/epic.yaml` `status: in-progress` |
| A10 | Re-evidence the protected-tag rules (`release-tags` ruleset, F-02, secret scanning), and decide whether the forge release and a scoped Gitea bot token are wanted. | Maintainer | F10, F12 |
| A11 | Resolve BL-E014-070 (15 legacy items failing `audit-issues`) so that `audit-issues` can serve as clean evidence. | Maintainer / l3io-doctor triage | F1 |

## Acceptance verdict

**accepted-with-open-items**. The criteria are profiled from the epic goal; the epic declares no ACs of its own.

| Goal clause | Evidence | Met |
|---|---|---|
| Restart, PKCS12, ACME parsing and settings actually work | S01-001..010 done; live-host test A–F | Yes. The BL-E014-105 and 107 gaps are filed. |
| Harden the CI supply chain and destination gating | S02-001, S02-002 done; BL-E014-075 and 078 fixed | Yes. BL-E014-079 and 108 are open. |
| Repair the decision record | S02-003 done (`tests_passing: false` per F1, pre-existing BL-E014-070) | Yes |
| Close E012 | S02-004 done (`tests_passing: false` per F1) | Yes |
| Release 0.3.0 from protected tags | Run 38281339396 success; PyPI, Docker Hub and Gitea at 0.3.0 | Released. The protected-tag rules were not re-queried at release (F10). |

- No story is unfinished, and no Critical or High finding is open.
- Open items: BL-E014-105/106/107/108 (carried to E015), the five `tests_passing: false` flags (recorded as they are), F10–F12, and the E013 and E014 epic closures in state.

## Open questions

- Should a mechanical gate read `tests_passing: false` as blocking? If so, F1 must be resolved (A1) before any epic gate can pass on these five stories without a human override.
- Is "from protected tags" satisfied by the rulesets configured earlier, or does it need evidence at release time (A10)?

## Assumptions

- Epic E014 was taken from the invocation (`-H E014`). `detect-epic` did not run because `sprint-status.yaml` does not exist; the completeness check used `pm-status show --epic E014` instead (17/17 done, `pending_stories` empty).
- The machine verdict `accepted-with-open-items` was rendered headless, with no human decision.
- The criteria were profiled from the `epic.yaml` goal.
- Phase 5's `sprint_status.py update` was not run (no file, and the brief forbids state changes). No `--set-action-status` transitions were proposed, because there are no prior-epic action items in a sprint-status file.
- The carry of BL-E014-105..108 to E015 "0.3.1" is recorded as the maintainer's decision, as given in the brief. Only BL-E014-106's severity change (`046016b`) is evidenced in state.
- All action items are proposals.
