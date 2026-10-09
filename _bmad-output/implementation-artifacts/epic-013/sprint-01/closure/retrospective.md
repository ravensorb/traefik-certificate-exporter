# E013 / S01 — sprint retrospective

Date: 2026-10-09. Scope: sprint S01 of E013 (standard CI/CD pipeline, ADR-0035). This is a short sprint
retrospective, not the full epic retrospective.

Sources: story docs `stories/E013-S01-00{1..5}.md`, `closure/notes-*.md`, `closure/review-*.md`,
`pm-status.py show --epic E013 --sprint S01`, and the per-story state files in
`state/active/epic-013/sprint-01/`.

## Stories

| Story | Title | Status | Review (C/H/M/L) |
|---|---|---|---|
| E013-S01-001 | Versioning and local tooling | done | 0/0/1/3 |
| E013-S01-002 | New workflows: build, ci, dev, release; remove old workflows and `tests/ci` | done | 0/0/1/2 |
| E013-S01-003 | Retire remaining legacy pipeline surface; docs and ADR statuses | done | 0/0/3/6 |
| E013-S01-004 | Live verification on GitHub, Gitea 1.27 and local act | blocked (carried over) | — |
| E013-S01-005 | Pipeline follow-ups from E013 review | done | 0/0/2/2 |

4 of 5 done. Carry-over: 1 (E013-S01-004 → E013-S02-001).

Backlog closed in-sprint: 9 keys by S01-003 (BL-E011-002/-004/-031, BL-E012-001/-002/-009/-010/-011/-012)
and 12 by S01-005 (BL-E013-003..-006, -008, -009, -011..-016). Filed in-sprint and still open:
BL-E013-007 (zizmor `self-repository` suppression awaiting ratification), BL-E013-017 (AD-7/AD-12/AD-18 wording).

## Velocity vs estimate (done stories only)

| Story | man_hours est → act | elapsed_hours est → act | tokens_k est → act | cost est → act |
|---|---|---|---|---|
| S01-001 | 11.73 → 8 | 1.83 → 0.35 | 338 → 6,747 | 1.40 → 4.83 |
| S01-002 | 17.69 → 12 | 1.06 → 0.53 | 350 → 7,381 | 1.45 → 6.75 |
| S01-003 | 11.73 → 14 | 1.83 → 0.30 | 338 → 14,013 | 1.40 → 12.96 |
| S01-005 | 13.58 → 10 | 1.48 → 0.21 | 3,519 → 8,044 | 2.99 → 5.67 |
| **Total** | **54.73 → 44 (0.80x)** | **6.20 → 1.39 (0.22x)** | **4,545 → 36,185 (8.0x)** | **7.24 → 30.21 (4.2x)** |

HITL hours: estimated 0.61, actual 0.

- Man-hour estimates were close (0.80x overall; only S01-003 overran, 1.19x).
- Elapsed time was overestimated about 4.5x.
- Token and cost estimates were badly low: 8x on tokens, 4.2x on cost. S01-003, a docs-heavy sweep,
  was worst at 41x tokens and 9.3x cost.
- The estimates look templated. S01-001 and S01-003 carry identical estimate blocks, and so do S01-004
  and S01-005. The sprint-level man-hour range (94.31–133.31) does not reconcile with the sum of its
  five story estimates (68.31).

## Blockers

- **E013-S01-004 is blocked by design.** Live verification needs the maintainer's GitHub and Gitea
  runners and the `PUBLISH_*` secrets. The maintainer moved it to E013-S02-001. The state note says to
  close S01-004 as done, pointing at E013-S02-001, once that story completes. Its local-act cell is
  already largely evidenced: S01-002 ran `ci.yaml`, `dev.yaml` and `release.yaml` under act 0.2.89 with
  exit 0, and so did S01-005 for `dev.yaml`.
- **act artifact protocol (BL-E013-010, resolved in-sprint).** upload-artifact v7 failed under act 0.2.89
  (`unknown field "mime_type"`). The first fallback, v6.0.0, still failed: it hit the second failure in
  nektos/act #6114 (signature padding). The fix was an orchestrator-run matrix, which chose upload v5.0.0
  and download v6.0.0, plus a Dependabot major-version ignore with a revisit condition. A related
  build-record upload from `docker/build-push-action` was turned off with
  `DOCKER_BUILD_RECORD_UPLOAD: "false"`.
- **Host environment.** The global Poetry could not install `requires-plugins` because of a `ruamel.yaml`
  conflict from an unrelated package. The workaround was `uvx --from poetry==2.4.2`. It is not a repo
  defect.

## What went well

- No CRITICAL or HIGH review finding in any of the four stories. Every MEDIUM was fixed in one fix pass,
  and the LOWs were deferred to backlog keys, all of which S01-005 then closed.
- Evidence was concrete. Each claim was backed by a recorded run:
  - version resolution was tested in throwaway clones;
  - a planted `ghp_` token proved `gitleaks-history` works;
  - `just release` refusal cases were run against a local bare origin;
  - the five-case registry-guard matrix was run;
  - the gitleaks exempt set was diffed against the trace.
- Deriving from the source of truth, not hand-kept lists (global rule 4), paid off. Rebuilding
  `docs/architecture.md` §6 from the ADR files corrected seven stale markers that the old hand-kept
  table had wrong.
- Where mechanical coverage was removed, it was stated plainly in prose (global rule 3). This covers the
  gitleaks no-`paths` rule, the no-`env.ACT` rule and the ruff Markdown exclusion, which are now held
  by CODEOWNERS review only.
- Story scope was handed off cleanly. S01-001 recorded what S01-002 would make green, and S01-002
  listed exactly what it left for S01-003.

## What didn't go well

- **Token and cost estimates were far off** (see velocity). Calibration from this sprint should feed
  the next estimate pass.
- **The spine's artifact pins were not tested against act before they were specified.** The v7/v8 pins
  in AD-5 conflicted with AD-6's three-runner portability. It took two pin iterations and an
  orchestrator matrix to resolve.
- **zizmor's `self-repository` audit (v1.30.0+) conflicts with AD-6 portability.** It was suppressed
  inline in three places and is still awaiting architect ratification (BL-E013-007).
- **Story S01-003 under-swept.** Its review found 3 MEDIUM and 6 LOW, the highest count in the sprint.
  The worst were dropped warnings: that publish variables carry publication authority, and how far a
  leaked credential reaches. The MEDIUMs were fixed in-story. The LOWs needed a whole extra story
  (S01-005).
- **Story text had internal ambiguities that the developer had to resolve:**
  - S01-001's "files S01-002 deletes" did not match the "five legacy workflows" named in its own
    edge-case text;
  - `mypy` `strict` inside overrides leaked globally, which forced edits outside Files in scope;
  - an unrecorded `just release` precondition had to be added.
- **The S01-005 review found the act evidence missing at review time** (F-1). Evidence should be
  produced before review is requested.
- **Sprint state hygiene.** `pm-status show` reports the sprint `status=backlog` even though 4/5
  stories are done.

## Action items

1. **E013-S02-001 (maintainer):** run the live GitHub and Gitea 1.27 cells. Record the run URLs,
   versions, tags and digests. Flip ADR-0035 to `Accepted`. Then close E013-S01-004 as done with a
   resolution pointing at E013-S02-001.
2. **Gitea check in E013-S02-001:** confirm that the node20 artifact pins (upload v5.0.0, download
   v6.0.0) work on GitHub-hosted runners and on Gitea `act_runner`. The S01-002 notes leave this open.
3. **Architect:**
   - ratify or amend AD-5 for the `self-repository` suppression (BL-E013-007);
   - resolve the AD-7/AD-12/AD-18 wording (BL-E013-017);
   - reconcile the ADR-0035 and ADR-0033 supersede-vs-amend disagreement recorded in the S01-005 notes.
4. **Estimation:** recalibrate the tokens_k and cost models from this sprint's actuals (8x / 4.2x
   under), and stop copying estimate blocks between unlike stories.
5. **Spine authoring:** before the spine pins a third-party action, test it on every runner AD-6
   requires.
6. **Process:** produce the required verification evidence (for example the act runs) before requesting
   review, not in response to it.
7. **State:** reconcile the S01 sprint status in `state/active/epic-013/sprint-01/sprint.yaml` at sprint
   close.
8. **Revisit trigger:** when nektos/act PR #6174 ships in a release, lift the Dependabot major-version
   ignores on upload-artifact and download-artifact.
