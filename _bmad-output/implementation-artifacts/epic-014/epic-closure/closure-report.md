# E014 epic closure report

- **Epic:** E014 — Ship 0.3.0: make restart, PKCS12, ACME parsing and settings actually work; harden the CI supply chain and destination gating; repair the decision record; close E012; release 0.3.0 from protected tags.
- **Final status:** done (closed 2026-10-12), archived. Verdict: accepted with open items (see `retrospective.md`).
- **Release:** 0.3.0 — PyPI 0.3.0, Docker Hub 0.3.0/0.3/latest (GitHub release run 38281339396, tag `v0.3.0` at `046016b`), Gitea 0.3.0 (local `act` run on `c7394e2`; see AD-1 / RT-2).
- **Closure session:** l3io-pm-20261011T161302Z-43c8ef. Epic diff reviewed: `git diff 364cd49..HEAD` (79 files, +12,930/−1,990).

## Estimate vs actual

| Metric | Estimate (low–high) | Actual | Notes |
| --- | --- | --- | --- |
| elapsed_hours | 19.86–24.37 | 9.71 | sprints 9.49 + epic closure 0.22 |
| man_hours | 305.76–334.8 | 230 | epic-level counterfactual, re-assessed from the delivered diff before reading the estimate |
| hitl_hours | 1.23–1.43 | 0.1 | sprint sums; epic closure ran headless (0 HITL) — `set-actual` skipped the hitl closure sample as a zero residual, which is the true value here, not a capture error |
| tokens_k | 149,766–170,188 | 202,906.09 | input 3.598 · output 227.413 · cache_write 9,069.54 · cache_read 193,605.537 (sprints + closure window from 20:52Z via `pm-status usage --since`) |
| cost (USD) | 116.65–132.54 | 159.19 | derived by `set-actual` |

Not captured in any node: the post-sprint-02 work (c7394e2, e55dca7, 9f05d19, 046016b — AR-3 gate, Gitea live publish, live-host test) ran in sessions outside any sprint or this closure window, so its spend is unattributed. The epic-level `orchestration` block (§4) was not written: the orchestrator's own coordination spend for this epic is not separable from its multi-epic session by this closure agent; sprint-level orchestration blocks exist (S01 12,755.2k, S02 25,854.33k tokens).

## Sprint velocity

| Sprint | Stories | elapsed_hours | man_hours | tokens_k | cost |
| --- | --- | --- | --- | --- | --- |
| S01 | 10 | 3.62 | 78 | 93,750.89 | 69.95 |
| S02 | 7 | 5.87 | 52 | 91,507.01 | 76.82 |

## Retrospective learnings

See `retrospective.md` (written by bmad-retrospective, headless). Top items:

- Keep `tests_passing` meaningful: pm-status needs an expected-failure mode (5 of 17 done stories read as failing).
- Run every story verification row against the tree before committing the story.
- Check the spine's adopted mechanisms before writing a guard.
- End-to-end dry runs and a live-host parallel test found defects unit gates could not; also verify the release lands from one run with one digest.
- Flat per-story estimates hid 0.27x–5.4x elapsed variance.

Honest-state items carried as-is: `completion_evidence.tests_passing: false` on E014-S01-008, E014-S02-003, E014-S02-004, E014-S02-005, E014-S02-006 (recording artifacts and the pre-existing BL-E014-070 audit), documented in the sprint closure reports. No exit codes were rewritten.

## Epic-level reviews

### Architectural drift (`arch-drift-review.md`) — Blocker: 0, Major: 2, Minor: 6

- **AD-1 (MAJOR)** 0.3.0 shipped as two image digests (Gitea `244015fe…` from `c7394e2` via local act; Docker Hub `e3be0498…` from `046016b`), no GHCR 0.3.0, no forge release — E014-S02-007 AC 6/8/9 unmet, unrecorded. Disposition: spec-proposal → `spec-proposals/AD-1.md`, BL-E014-111.
- **AD-2 (MAJOR)** `import-linter` and `mirrors-mypy` hook dependency closures resolve unpinned/unaudited in the dist-building `build` job; AD-3/ADR-0042 overstate coverage. Disposition: spec-proposal → `spec-proposals/AD-2.md`, BL-E014-112.
- AD-3..AD-8 (MINOR) → BL-E014-113..118.

### Red team (`redteam-report.md`) — Critical: 0, High: 1, Medium: 1, Low: 2, Observations: 2

- **RT-1 (HIGH)** the base image's `init-adduser` (`lsiown abc:abc /config`) hands `/config` to the PUID account on every boot, contradicting ADR-0030; demonstrated that the PUID account can rewrite config so the next root-mode start runs its hook as root. → BL-E014-119 (High).
- **RT-2 (MEDIUM)** Gitea 0.3.0 published from a workstation act run with an instance-admin token, against ADR-0039; rotate the token. → BL-E014-120 (Medium).
- RT-3, RT-4 (LOW) → BL-E014-121, BL-E014-122. RT-5/RT-6 observations: distributions reproducible across forges; untrusted store values validated before reaching sinks.

### Gate deviation, stated

`epic-closure.md` requires CRITICAL/HIGH and MEDIUM redteam findings, and BLOCKER/MAJOR drift findings, to be fixed or ADR-justified before closure. Per the orchestrator's closure directive (0.3.0 is released; fix only BLOCKER/CRITICAL at epic closure; defer the rest to E015 "0.3.1"), **RT-1 (HIGH), RT-2 (MEDIUM), AD-1 and AD-2 (MAJOR) were deferred to the backlog, not fixed and not ADR-accepted.** No ADR was written to accept them, because accepting a demonstrated root-escalation path is a maintainer decision. E015 triage should take RT-1 first.

## Issue triage

Open E014 backlog after closure: **High 1, Medium 26, Low 85** (112 items). Promoted: 0 (no Low item's risk changes given the full-epic view; RT-1 was filed directly at High).

Carried forward to E015 "0.3.1" (maintainer decision): BL-E014-105 (watch mode misses atomic-rename store replacement, Medium), BL-E014-106 (≈1–1.5 s per certificate export pass, Medium), BL-E014-107 (legacy detection misses pre-confuse env names, Low), BL-E014-108 (setup-buildx-action v4 `config` input renamed, Medium) — plus this closure's BL-E014-111, 112, 119, 120.

## ADRs produced

ADR-0040, 0041, 0042, 0043, 0044, 0045, 0046, 0047, 0048 (`docs/adr/`), plus amendments to 0001, 0002, 0003, 0014, 0016, 0017, 0023, 0024, 0025, 0026, 0027, 0028, 0030, 0035, 0036, 0039 in the epic diff.

## Spec changes

| Finding | Disposition | Commit / proposal | Backlog |
| --- | --- | --- | --- |
| SD-01-1 (S01) | resolved-in-code | — | — |
| SD-01-2 (S01) | resolved-in-code | — | — |
| SD-02-1 (S02) | resolved-in-code | — | — |
| SD-02-2 (S02) | spec-updated (CI spine AD-8; ADR-0046 link) | `df7b4bf` | BL-E014-109 |
| ADR-0042 link (CI spine AD-3) | adr-link | `2c13530` | BL-E014-110 |
| AD-1 (epic) | spec-proposal | `spec-proposals/AD-1.md` | BL-E014-111 |
| AD-2 (epic) | spec-proposal | `spec-proposals/AD-2.md` | BL-E014-112 |

- Spec index: 35,353 bytes, 133 sections (5 specs). `build` warned it exceeds the 16,384-byte budget.
- Ranges in `Sections read:` footers: the epic arch review lists 12 ranges; story pointers resolved to nothing (`sections`: "no resolvable pointers").
- Spec sync share of fresh tokens: spec sync ran inline in the closure agent (no `l3io-spec-sync` subagent), so it is not separately measurable; it is included in the closure window total.
- `check-pointers --all`: 5 story files with broken pointers, all legacy `epic-007` stories (pre-business format); none in E014.

## Follow-ups

- **E013 epic closure has not run** although all its stories are done — run it separately.
- Plan E015 "0.3.1" from BL-E014-105..108, 111, 112, 119, 120 (RT-1 first).
- Retrospective also flags: production on rwusdckrls6 pulls `ghcr.io/…:latest`, which has no 0.3.0 (ties to AD-1); `release-tags` ruleset not re-checked at release time.
