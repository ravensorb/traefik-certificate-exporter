# Retrospective — E015 sprint 01 (sprint-scoped)

Date: 2026-10-12. Scope: sprint 01 only (E015-S01-001..004). Written inline: `bmad-retrospective`
is an epic-scoped review, and the epic is not complete, so its acceptance decision does not apply here.

Sources: story files (headers/ACs), `closure/notes-E015-S01-00{1..4}.md`,
`closure/review-E015-S01-00{1..4}.md`, `pm-status.py show --epic E015 --sprint 01`, and the
facts established at sprint closure.

## Outcome

| Story | Class | Status | Review result | Fix iterations |
|---|---|---|---|---|
| S01-001 root-mode settings trust (ADR-0049/0050) | complex | done | 1 HIGH, 2 MEDIUM, 5 LOW; re-review 2 MEDIUM, 3 LOW | 2 |
| S01-002 `validatekeys` + `.pfx` fingerprint sidecar | complex | done | 1 MEDIUM, 3 LOW | 1 (docs only) |
| S01-003 watch mode detects rename | standard | done | 2 LOW | 0 |
| S01-004 pre-confuse `TRAEFIK_*` warnings | standard | done | 5 LOW | 0 |

4/4 done. Carry-over: 0.

## What went well

- **Fail-first evidence on every story.** All four notes paste failing output against the
  unchanged tree before the product change (e.g. S01-002's RSA-4096 fixture, which exposed a cost
  the EC P-256 fixtures had hidden).
- **Guards derived from the source of truth and attacked on scope (global rule 4).** S01-001's
  trust map is derived from `config_default.yaml` with a planted leaf; S01-004's legacy-name guard
  is derived from `git log -G appParams` history and attacked with a second, later-deleted
  translator. S01-003's reviewer ran a planted-violation probe (10/10 caught).
- **Review caught a real security hole before closure.** S01-001 F1 (HIGH): a root exporter
  loaded `abc`-writable `/config/.env` and kept `LD_PRELOAD`/`DOCKER_HOST` in the hook's
  environment. Fixed in iteration 1 with an admitted set derived from `ROOT_SETTING_TRUST`.
- **F10 fix delegated to the tool.** The regex for `noqa` spellings was replaced by asking ruff
  which TID251 reports a suppression hides, instead of re-implementing ruff's suppression rules.
- **LSIO constraint held.** No Dockerfile or s6 change; `/config` stays `PUID`-owned (review probe P1).
- Elapsed time was well under estimate (2.31 h vs 4.24 h).

## What did not go well

- **Token actuals were over-recorded by 8-16%.** Transcript records were not deduplicated. They
  were corrected at closure to the dispatch-bracket measure, but calibration samples had already
  been taken at the inflated values and could not be replayed, so this sprint's calibration input
  is biased high.
- **Scope drift on S01-001 needs ratification.** Fix iteration 1 narrowed root-mode `.env`
  handling beyond AC 3 (only `any-source` names admitted; every other newly added name removed),
  recorded as an ADR-0049 amendment. It is the right security call, but it changed an accepted
  decision without the maintainer, and is still unratified.
- **The pre-commit mypy hook missed two errors.** S01-001 introduced two mypy errors in
  `settings.py`; the hook's isolated env lacks `confuse`, so `ignore_missing_imports` types it as
  `Any` and the errors were invisible. Found and fixed only at closure. `just check` was green
  over a type check that was not checking this code path.
- **ADR dates were pre-filled** as 2026-10-13 and had to be corrected to 2026-10-12.
- **Guard claims overstated their reach, twice in one story.** S01-001 F2 (banned-API list
  presented as complete) recurred one ring out as F12 (stdlib functions that spawn internally),
  and F3's suppression regex missed forms (F10, F11). Global rule 3's "prose that overstates its
  own coverage" pattern.
- **Story prep defect.** S01-004's `-G appParams` derivation started matching planning artifacts
  committed after the story was written; handled in implementation via `_SCAN_EXCLUDE`.
- **Estimates look class-templated, and fix factors were inverted.** Both complex stories carry
  identical estimates (17.11 mh, fix_factor 1.25) and both standard stories identical ones
  (9.99 mh, fix_factor 2.74). The complex stories took 3 fix iterations between them; the standard
  stories took none.

## Velocity vs estimate

| Story | Man-h est / act | Elapsed h est / act | Cost est / act (sprint total) |
|---|---|---|---|
| S01-001 | 17.11 / 24 | 0.97 / 1.30 | |
| S01-002 | 17.11 / 24 | 0.97 / 0.45 | |
| S01-003 | 9.99 / 8 | 1.15 / 0.21 | |
| S01-004 | 9.99 / 10 | 1.15 / 0.35 | |
| **Sprint** | **54.2 / 66 (122%)** | **4.24 / 2.31 (54%)** | **26.16 / 42.11 (161%)** |

Tokens (corrected, dispatch-bracket): 52,665.8k total; S01-001 alone is 29,222k (55%), driven by
its two fix iterations. HITL: 0.09-0.16 h estimated per story, 0 recorded. Complex stories ran
~40% over on man-hours; standard stories landed on or under estimate. Cost overran most, which is
consistent with fix-iteration token spend not being reflected in the complex-story fix factor.

## Action items

| # | Action | Owner | Due |
|---|---|---|---|
| A1 | Maintainer ratifies (or rejects) the ADR-0049 amendment that narrows root-mode `.env` beyond S01-001 AC 3. | Maintainer | Before E015 epic closure |
| A2 | Make the mypy pre-commit hook see real types: add `confuse` (and other typed runtime deps) to `additional_dependencies`, or run mypy via `poetry run` as a `repo: local` hook; add a planted type error in a `confuse`-typed path that must fail the gate. | Dev | Next sprint |
| A3 | Deduplicate transcript records before computing story token actuals, and re-take calibration samples only from the corrected measure; flag this sprint's existing samples as biased high. | PM tooling | Next sprint |
| A4 | Stop pre-filling ADR dates at planning time; set the date when the ADR is written, or check it against the commit date. | Planning | Next sprint |
| A5 | Re-derive fix_factor per story risk rather than per class: security/guard stories in this sprint needed 2 iterations at 1.25; standard stories needed 0 at 2.74. | Planning | Before next estimate |
| A6 | Confirm the deferred LOW findings are in the backlog: S01-001 F4-F8, F11-F13; S01-002 R2-R4; S01-003 R1 (scheduling-dependent negative assertions), R2; S01-004 F1-F5. | Orchestrator | Before E015 epic closure |
| A7 | When a story states a guard's coverage, require its limit list to be reviewed for "next ring out" omissions (cf. F2 -> F12). | Review | Ongoing |

## Assumptions

- Disposition of S01-003 and S01-004 LOW findings is inferred: no fix iteration is recorded in
  their notes, so they are treated as deferred (A6 asks for confirmation).
- The sprint node reports `status=backlog` while all four stories are `done`; treated as state
  not yet rolled up at closure, not as carry-over.
