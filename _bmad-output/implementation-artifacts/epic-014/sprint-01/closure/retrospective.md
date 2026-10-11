# Sprint retrospective: E014 sprint 01 (Product correctness)

- Scope: sprint retrospective for E014-S01 only, not an epic retrospective. There is no epic acceptance decision here.
- Date: 2026-10-11
- Sources, and nothing else: the state nodes `state/active/epic-014/sprint-01/E014-S01-0{01..10}.yaml` and `sprint.yaml`, the hand-offs `closure/notes-E014-S01-*.md` and `closure/review-E014-S01-*.md`, the `BL-E014-*` entries in `state/issues.yaml`, and `git diff --stat` / `git status` on the uncommitted working tree, excluding `.agents/`, `.claude/`, `_bmad/` and `uv.lock`.
- Method: done inline. The `bmad-retrospective` skill is built for epic retrospectives and ends in an acceptance decision, so it did not fit this sprint-level brief.

## 1. Stories completed

All 10 stories are `status: done`. Carry-over: 0.

| Story | Title | Review (C/H/M/L) | Fix iterations | tests_passing | Files changed |
|---|---|---|---|---|---|
| E014-S01-001 | Docker SDK 7.2 and a restart path that really works | 0/0/1/4 | 1 | true | 10 |
| E014-S01-002 | PKCS12 export: passphrase, intermediates, chain parsing, build before replace | 0/0/2/3 | 1 | true | 11 |
| E014-S01-003 | CA-agnostic, null-safe ACME store parsing with per-resolver isolation | 0/0/3/2 | 1 | true | 6 |
| E014-S01-004 | Settings that actually take effect: CLI dest, env names, log level | 0/0/1/3 | 1 | true | 14 |
| E014-S01-005 | Container lifecycle: run-once vs watch under s6 | 0/1/2/3 | 1 | true | 15 |
| E014-S01-006 | Restart cooldown: defer, don't drop (with ADR) | 0/0/2/4 | 1 | true | 17 |
| E014-S01-007 | Dependency refresh and pip-audit gate | 0/0/1/4 | 1 | true | 11 |
| E014-S01-008 | CLI/output hygiene: redaction, usage text, flag errors | 0/0/1/1 | 0 | **false** (see 5.1) | 8 |
| E014-S01-009 | Legacy and unknown setting-name detection with actionable warnings | 0/0/4/4 | 1 | true | 9 |
| E014-S01-010 | Hook and notifications only for changed domains; postexportcommand redaction | 0/0/2/3 | 1 | true | 16 |

Working-tree footprint (uncommitted): 72 tracked files changed, +8,099 / -1,842. The largest are `libs/certificate_exporter.py` (+/-1,103), `libs/docker.py` (466), `tests/libs/test_docker.py` (1,194), `tests/libs/test_certificate_exporter.py` (1,155) and `poetry.lock` (2,324). There are also 17 new untracked files outside `_bmad-output/`: ADRs 0040 to 0045, `libs/legacy_settings.py`, `libs/suggest.py`, the s6 `finish` script, and 8 new test modules, including the container tests `test_container_{pkcs12,restart,run_once}.py`, `test_s6_run_mode.py` and `test_settings_surface.py`.

`sprint.yaml` still says `status: backlog` with all 10 stories done. Sprint closure needs to move it.

## 2. Velocity: estimate vs actual

Every story was estimated with the same numbers: 0.75 h elapsed, 10.58 man-hours, 0.05 HITL hours, 7,248 k tokens and $5.91, all `classification: standard` with fix_factor 2.8333. The ratio column is actual divided by estimate.

| Story | Elapsed h (act, ratio) | Man-hours (act, ratio) | Tokens k (act, ratio) | Cost $ (act, ratio) |
|---|---|---|---|---|
| S01-001 | 0.25, 0.33 | 8, 0.76 | 4,309, 0.59 | 3.49, 0.59 |
| S01-002 | 0.40, 0.53 | 9, 0.85 | 7,477, 1.03 | 5.55, 0.94 |
| S01-003 | 0.22, 0.29 | 10, 0.95 | 3,997, 0.55 | 3.30, 0.56 |
| S01-004 | 0.30, 0.40 | 8, 0.76 | 8,380, 1.16 | 5.98, 1.01 |
| S01-005 | 0.40, 0.53 | 10, 0.95 | 8,866, 1.22 | 6.12, 1.04 |
| S01-006 | 0.50, 0.67 | **20, 1.89** | **14,194, 1.96** | **9.66, 1.63** |
| S01-007 | 0.30, 0.40 | 8, 0.76 | 5,939, 0.82 | 4.49, 0.76 |
| S01-008 | 0.20, 0.27 | 6, 0.57 | 3,948, 0.54 | 3.21, 0.54 |
| S01-009 | 0.30, 0.40 | 10, 0.95 | 6,101, 0.84 | 4.72, 0.80 |
| S01-010 | 0.25, 0.33 | 6, 0.57 | 6,733, 0.93 | 4.90, 0.83 |
| **Sum** | **3.12 vs 7.5, 0.42** | **95 vs 105.8, 0.90** | **69,944 vs 72,480, 0.97** | **51.42 vs 59.10, 0.87** |

Actual HITL hours were 0 for every story, against 0.05 estimated per story.

Observations:
- **Elapsed time was overestimated on every story**, by 0.27x to 0.67x. Over the sprint it ran at 0.42x.
- **Tokens and man-hours were close in aggregate** (0.97x and 0.90x), but the spread per story was wide. S01-006 used about twice its estimate on man-hours and tokens. S01-008 and S01-010 used about half on man-hours.
- **The flat estimate did not tell stories apart.** S01-006 was the only story that carried an ADR (0045) and a new restart policy, and it changed 17 files. S01-008 changed 8. Both were planned identically. For the next plan's estimates: size per story, or at least weight by expected ADR and container-test work.
- The sprint-level envelope in `sprint.yaml` (146 to 206 man-hours, 9.9 to 12.6 elapsed hours) includes closure and orchestration ratios. Those phases are not in the story actuals, so this table compares story level only.

## 3. Blockers

- **No story was blocked.** Every story reached `done` with 0 HITL hours.
- **One item needs a maintainer decision and stays open.** BL-E014-017 is covered in section 6.
- The other hold-ups were rework, not blockers:
  - Docker SDK 7.2 behaviour in S01-001: `ping()` with a pinned `version` raises `requests.ConnectionError`, which forced the construction-inside-`raises` test form.
  - A shellcheck `types` quirk in S01-005: upstream `types: [shell]` skipped the `with-contenv` executables.
  - pip-tools/pip incompatibility and a failed `poetry add` setup in S01-007.

## 4. Fix iterations

- Nine stories recorded `fix_iterations: 1`. S01-008 recorded 0.
- No story needed a second review cycle.
- Review findings over the sprint: 0 critical, 1 high, 19 medium, 31 low.
  - The one high was S01-005 F1. It was resolved by correcting the claim rather than the Dockerfile, and is now BL-E014-017.

Recurring causes of rework:
1. **The notes file was missing when review ran, in 5 of 10 stories.**
   - S01-002 R-01, S01-006 M2, S01-008 F-1, S01-009 M4 and S01-010 F2 each raised a MEDIUM for it.
   - S01-003 R-03 was a related claim finding, also closed by writing the notes.
   - The workflow writes notes after review, but the ACs need them before review. Each of these MEDIUMs cost a finding and a disposition for no product gain.
2. **The first `just check` run failed on `ruff format`.**
   - It happened in S01-004 (notes row 12), S01-008 (notes row 11) and S01-010 (review F1, an unsorted import and an unformatted test line).
   - Running `ruff format` and `ruff check --fix` before the first gate run would remove this.
3. **Overstated claims in docs and docstrings were the most common finding kind.** Examples:
   - S01-007 F1: "every poetry.lock group" is false for marker-gated entries.
   - S01-009 M3: the docstring overstated the marker rule's coverage.
   - S01-005 F1: the claim that `watchforchanges: false` from a config file works in the image.

   This is global rule 3 at work: prose that claims more coverage than its check gives.

Backlog filed during the sprint (all `status: backlog`):
- Medium: BL-E014-017 and BL-E014-023. BL-E014-023 is pip-audit skipping marker-gated lock entries.
- Low: BL-E014-011, 013, 014, 015, 016, 018, 019, 020, 021, 022, 024, 025, 026.
- Resolved during the sprint: BL-E014-001 and BL-E014-007, by S01-009.

## 5. Evidence-quality findings

### 5.1 E014-S01-008: `tests_passing` is false and will stay false

- **Facts.** Entry 0 of `completion_evidence.test_runs` is `poetry run pytest -q tests/libs/test_settings.py tests/libs/test_cli_args.py tests/test_settings_surface.py (fail-first, pre-change code)` with `exit_code: 1`. pm-status derives `tests_passing` from the last run of each distinct command string. No other run carries that label, so it stays red for good and `tests_passing` is `false`.
- **Closure was right not to add a green run.** The label denotes the pre-change code, and running that suite there really exits 1. A green entry under the label would be false.
- **The suite is green on current code.** The same suite is recorded with exit 0 under the plain command string (entry 14, 74 passed). `just check` is green too (entry 13).
- **So the red flag is an artefact of how evidence is recorded, not a product failure.** But anything that reads `tests_passing` mechanically will see this story as failing.
- **Root cause.** `pm-status add-test-run` has no way to record an expected failure. A fail-first run either poisons `tests_passing` (S01-008) or has its exit code inverted (5.2).
- **Action item A1.** Give pm-status an expected-failure / fail-first recording mode: a field such as `expect: fail` that is kept apart from the `tests_passing` derivation and still stores the real exit code.
- **Action item A2, until A1 ships.** Record fail-first runs in the notes only, not in `test_runs`. S01-002, S01-006, S01-007 and S01-010 already did this. Their notes say fail-first runs on a pre-change tree are evidence for the "Fails before" column, not runs of the story's result.
- **Contrast.** S01-001 recorded its fail-first runs under the same command strings as the later green runs. That keeps the real exit codes, and later runs supersede them, so it works only when the label is identical.

### 5.2 E014-S01-009 (following S01-004): synthetic exit codes in `test_runs`

- **Facts for S01-009.**
  - Probes 7a, 7b, 8, 9a and 9c were first recorded with the raw pytest exit code 1, at entries 7, 8, 9, 10 and 12.
  - The same five labels were then appended again with `exit_code: 0`, at entries 13 to 17. That 0 is a verdict ("0 = failed as expected"), not the exit code of the command string.
  - `notes-E014-S01-009.md` says this was deliberate so that "the derived `tests_passing` reflects probe verdicts".
  - Entries 18 (probe AG-5) and 21 (probe review-M3) were recorded only with the synthetic 0 ("recorded as pass when it fails"). For those two there is no raw entry at all.
- **Finding.** In those entries `test_runs` no longer records what was executed. A reader or tool sees the same command with exit 1 and then exit 0, and would conclude that the second run passed. In fact both runs failed, as intended. The labels are also prose ("probe row 7a (RESTART_CONTAINERS row deleted): …"), not runnable commands, so the entries cannot be replayed.
- **S01-004 did the same thing, in a smaller form.** Its entry 5 is `scope probe: docs/x-scope-probe.md + pytest …::test_documented_env_names_map_to_settings (expected exit 1; recorded as pass when it fails)` with `exit_code: 0`. It was recorded once, with the synthetic 0 only and no raw exit-1 entry. Its notes (row 5) show that the real run exited 1. So S01-004 started the inverted-exit convention, and S01-009 copied it and extended it with a raw-then-verdict pair.
- **Counter-examples in the same sprint.**
  - S01-005 (deviation 4) and S01-007 ("How the runs were recorded") ended probe shell lines with `rm` or `echo "exit=$?"`. The recorded exit code is therefore the real exit of the recorded command line, and the hook's own exit is printed and pasted into the notes.
  - S01-005 states it plainly: "not as a synthetic hook exit".
  - That form is honest, but the bite lives only in the notes.
- **Action item.** Same as A1: an expected-failure mode in pm-status, storing the real exit code plus the expectation, removes the reason to invert. Until then, use A2: record expected-failure probes in the notes, or record the real outer exit of a command line that captures the inner exit, as S01-005 and S01-007 did. Never record a synthetic exit code under a command label.
- **Effect on this sprint.** `tests_passing: true` for S01-004 and S01-009 depends partly on the inverted entries. The underlying behaviour is still evidenced: the notes paste the real outputs, and both stories' final `just check` and full-suite runs are real exit 0s. So no product claim is false. But the field is not trustworthy as recorded.

## 6. Open item needing a maintainer decision: BL-E014-017 (Medium)

- **Problem.** `docker/Dockerfile:128-129` sets `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true` and `_RUNATSTART=true`. The environment outranks the config file. So `watchforchanges: false` in `/config/config.yaml` is ignored in the image, and the config file cannot select run-once in the container.
- **Why it was not fixed in S01-005.** Removing the ENV defaults would switch every mounted config that omits the key to the packaged default, `false`, which means run-once. That is a behaviour change for existing users.
- **Current state.**
  - S01-005 corrected the claim, not the code: `docker/README.md`, `docs/operational.md` and ADR-0044 now say the env var is the container's run-once switch.
  - The issue is in `state/issues.yaml` as severity Medium, `status: backlog`, source review-E014-S01-005 F1.
- **This retrospective does not decide it.** It stays open for the maintainer.
- **Dependent item.** E014-S02-005 must reword the 0.3.0 release-note bullet "honours `watchforchanges: false` from any source: config file, env, …". `notes-E014-S01-005.md` flags this, and it holds whatever the decision is.

## 7. What went well

- **All 10 stories done in 3.1 elapsed hours against 7.5 estimated, with no blockers and no second review cycles.**
- **Fail-first discipline was consistent.** Every story recorded a pre-change failure for its new tests, in notes or in `test_runs`.
- **Guards were attacked at their scope, not only their rule, per global rule 4.** Examples:
  - S01-004's scope probe (`docs/x-scope-probe.md`).
  - S01-009's table-row, shallow-clone and marker probes.
  - S01-005's shellcheck plant, which exposed the `types: [shell]` exclusion.
  - S01-007's cold-cache offline probe, which corrected an imprecise "offline it fails" claim.
- **Decisions were recorded, not buried.**
  - Six new ADRs (0040 to 0045).
  - Deviations listed in notes (S01-002, S01-005).
  - Out-of-scope gaps filed as backlog rather than dropped silently: 15 items.
- **A pre-existing defect was found and fixed in scope.** S01-004 found test pollution: `globalLogger` was left at INFO by `test_app.py`, which default ordering had hidden.
- **The library-first rule was followed.**
  - S01-008 has a grep check that `difflib` is not hand-imported in `cli_args.py`, and suggestions go through the shared `libs/suggest.py`.
  - S01-001 uses the Docker SDK, not raw `requests`, and has a grep check for it.

## 8. What went badly

- **Evidence quality in `test_runs` (section 5).** Two incompatible conventions coexist: synthetic exit inversion (S01-004, S01-009) and notes-only or real-outer-exit (S01-002, 005, 006, 007, 010). One story (S01-008) has a red `tests_passing` that cannot be fixed honestly with the current tool.
- **Notes were written after review** in 5 stories, producing avoidable MEDIUM findings.
- **The first `just check` run failed on formatting** in 3 stories.
- **Overstated prose** was the most common review finding kind (claims in docs and docstrings beyond what the check covers).
- **Flat estimates** with a wide spread in actuals per story, from 0.54x to 1.96x on tokens.
- **Process deviation (S01-009).** Development was done by the story agent directly, not by a separately spawned dev subagent. The review stayed separate. The notes record this.

## 9. Action items

| # | Action | Owner (proposed) | Evidence |
|---|---|---|---|
| A1 | Add an expected-failure / fail-first recording mode to `pm-status add-test-run` that stores the real exit code plus the expectation and keeps it out of the `tests_passing` derivation. | l3io-pm tooling maintainer | 5.1, 5.2 |
| A2 | Until A1 ships: record fail-first runs and expected-failure probes in notes only (or as the real outer exit of a capturing command line, as S01-005 and S01-007 did). Never record a synthetic exit code under a command label. | Story agents, from E014-S02 | 5.1, 5.2 |
| A3 | Decide BL-E014-017: keep the image ENV defaults (env var is the run-once switch) or remove them (config file controls, behaviour change for configs omitting the key). | Maintainer | Section 6 |
| A4 | E014-S02-005: reword the 0.3.0 release-note bullet on `watchforchanges: false` to match whatever A3 decides. | E014-S02-005 | Section 6 |
| A5 | Write the story notes file before dispatching review. | Story agents / l3io-execute flow | Section 4, item 1 |
| A6 | Run `ruff format` and `ruff check --fix` before the first `just check`. | Story agents | Section 4, item 2 |
| A7 | Estimate stories individually, weighting ADR-bearing and container-test stories, rather than one flat per-story estimate. | l3io-plan (estimate) | Section 2 |
| A8 | Move `sprint.yaml` out of `backlog` at sprint closure. | Sprint closure | Section 1 |

## Closure review outcome

- Phases run: retrospective, clean-release + adversarial (one `bmad-review` pass), red team, UX (inline; `bmad-ux` Reviewer Gate is GUI-only), sprint architectural drift. None skipped.
- Fixed in closure: SD-01-1, SD-01-2 (MAJOR), ADV-1..ADV-4 (MEDIUM) in fix iteration 1; RT-3 (MEDIUM) and RT-6 (LOW, via ADV-3). 8 resolved.
- Deferred: 34 backlog items BL-E014-027..060 (8 Medium, 26 Low). RT-9 duplicates BL-E014-016.
- Evidence-quality note on the closure itself: the fix agent wrote its resolution note into the arch-drift Severity cell, which broke `check-dispositions` parsing; closure restored `MAJOR` and recorded the resolution via `spec-align disposition`.
- E014-S01-008 `tests_passing` stays false by derivation; no green run was recorded under the `(fail-first, pre-change code)` label because that label denotes the pre-change code, which does fail.
- BL-E014-017 was decided by the maintainer during closure (2026-10-11): resolved wontfix, env overrides the config file for all settings (CLI > env > config file > defaults); E014-S02-003 records it in the spine, ADR-0044 and operator docs. See `epic-014/execution-notes.md`.
