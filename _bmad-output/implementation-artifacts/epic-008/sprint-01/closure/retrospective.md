# Epic 8 / Sprint 1 — Retrospective

**Mode:** headless (`bmad-retrospective -H`), dispatched by `l3io-pm-execute` sprint-closure §1.
**Scope:** `E008` / `S01`, `work_type: MIXED`. **Diff range:** `72feefb^..HEAD` (`df6e5ed`), 8 commits.

## Summary

Four stories delivered the entire publication pipeline — `dev.yaml`, `release.yaml`, a reusable
`publish-image.yaml`, three composite actions, registered finalizers split by authority, and the
topology cutover with a recovery runbook — in 43 files, +8,888/−566, with the contract suite going
from 34 guards to 124 and the repo suite from 150 to 333 collected tests. Every story closed in a
single fix iteration against a full adversarial review, and the sprint's two most expensive events
were maintainer rulings that arrived *after* three stories were already marked `done`: "no Python
in the publication path" deleted 749 lines of shipped, tested script plus 613 lines of their pytest,
and "prefer an existing action" moved the alias action `@v1`→`@v2` and handed tag rendering to
`docker/metadata-action`. Nothing carried over — all four stories met their acceptance criteria —
but three review findings were deliberately deferred to the backlog and the sprint ran roughly
2× its man-hour estimate and 3× its elapsed estimate.

## Epic summary

| | |
|---|---|
| Stories | `E008-S01-001` … `-004`, **all four `done`** |
| Unfinished stories (`pending_stories`) | **none** |
| Carry-over story scope | **0** |
| Fix iterations | 1 per story (all four) |
| Diff | 43 files, +8,888 / −566, 8 commits `72feefb^..df6e5ed` |
| Contract guards | 34 → **124** (`tests/ci/test_workflow_contracts.py`) |
| Collected suite | 150 → **333** |
| Review findings | 0 critical, 8 HIGH, 22 MEDIUM, 23 LOW across four story reviews |
| Deferred to backlog | 3 (`BL-E008-002`, `-003`, `-006`) — all LOW |
| Verdict | **accepted-with-open-items** |

### Estimate versus actual

Derived from the four `state/active/epic-008/sprint-01/E008-S01-00*.yaml` files.

| | estimate | actual | ratio |
|---|---|---|---|
| man_hours | 55.0 (16.87 × 3 complex + 4.36 standard) | 110 (40 + 24 + 34 + 12) | **2.0×** |
| elapsed_hours | 2.63 | 8.0 (2.5 + 1.6 + 2.4 + 1.5) | **3.0×** |
| epic elapsed (`epic.yaml`) | 2.87 – 2.97 | 8.0 | **2.7×** |
| tokens_k / cost | 1,585–1,801k / $6.54–7.43 | **N/A** | not comparable |

`tokens_k: N/A` and `cost: N/A` on every story — the sprint ran under `runtime: other`, so no token
or cost calibration is available from this sprint. Recorded as a gap, not inferred.

### Evidence inventory

**Available and read in full:** four story state YAMLs; four story documents; four code-review
records (`closure/review-E008-S01-00*.md`); both architecture-gate reports
(`epic-008/arch/arch-gate-review.md`, `-2.md`); `state/issues.yaml` (`BL-E008-*`);
`state/events.jsonl`; `state/pm-calibration.yaml`; the 8-commit diff; the current worktree
(workflows, actions, `tests/ci/`, `docs/adr/0006|0010|0011`).

**Not available, and what that narrows:**

- **No `sprint-status.yaml`.** This project uses the sharded `state/` tree, so the
  `sprint_status.py detect-epic` gate did not run. The completeness check was performed instead
  against the four per-story YAMLs, each of which carries `status: done` — an equivalent check on
  the same source of truth, but not the script-backed one the skill specifies.
- **No E007 retrospective to check follow-through against.** `epic-007/` holds only
  `epic-closure/closure-report.md`, which records at line 24 that the sprint retrospective and the
  arch-review report were *themselves* among the artifacts lost. See "Previous-retro follow-through".
- **No token/cost actuals** (above).
- **No workflow run evidence.** See "Behavior verification".

## Findings

Each carries its source. Findings already fixed inside the sprint are not restated here — the four
review records hold them. What follows is what the *sprint as a whole* shows and what is still true
of the tree at `df6e5ed`.

### F-A1 — The dominant defect class of this epic is a guard that proves its rule over the wrong set

This is not an impression; it is the majority finding of both gates and all four reviews.

- **Gate 1** raised 30 findings (3 BLOCKER, 17 MAJOR, 10 MINOR). Six of the twenty blocking ones —
  **F2, F6, F10, F11, F12, F15** — are the same defect: a correct rule keyed on a hand-written
  tuple (`SECRET_FREE_WORKFLOWS`), a bare job name (`RELEASE_FINALIZER_JOBS`), job scope excluding
  workflow scope, a single file (`VERIFY_WORKFLOW`), the literal job name `plan`, and a publisher
  recognised only by `uses:`.
  Source: `epic-008/arch/arch-gate-review.md:70-104`.
- **Gate 2** re-ran the same review and states it outright: *"The failures are all of one kind…
  a guard was written, the rule it encodes is right, and the set it examines is smaller than the
  rule."* It planted fourteen violations against a scratch tree; **five passed a fully green
  33-test suite**, including `git push -f` onto `refs/tags/v1` from the registered finalizer, which
  ADR-0006 forbids in bold. Its verdict was **CHANGES REQUIRED** with 17 open items (1 BLOCKER, 10
  MAJOR, 6 MINOR); seven of those were new, and the new BLOCKER **N1** was structurally identical
  to gate 1's F1 — *"the remediation added rules faster than it added reach."*
  Source: `arch-gate-review-2.md:30-52, 100-118, 259-286`.
- **The same class then dominated the story reviews**, after both gates: review 001 MEDIUM-4 and
  MEDIUM-6; review 002 MEDIUM-4; review 003 M6; review 004 HIGH-1, MEDIUM-2, MEDIUM-5, MEDIUM-6.
  Review 004's HIGH-1 is the sharpest instance — "each event has exactly one owner" was enforced by
  comparing filter *strings*, so `push: {branches: ["ma*"]}` and `push: {tags: ["v1.*"]}` both
  passed while racing `dev.yaml` and `release.yaml`.
  Source: `closure/review-E008-S01-004.md:20-45`.

**What this says about process, not about any story:** the rule exists (global rule §4 — *"derive
the scope from the source of truth; never enumerate it by hand"*), it was cited by name in the gate
findings, and it was still violated in newly written guards *after* being raised twenty times. It is
enforced by review attention, and review attention is the thing that does not scale. There is no
meta-guard that examines a guard's scope derivation.

### F-A2 — Rework arrived after `done`, and the state machine has no vocabulary for it

Verified from commit timestamps against `events.jsonl` status transitions:

| story | marked `done` | commits that materially rewrote its delivered files afterwards |
|---|---|---|
| `-001` | 2026-09-02 12:30 EDT | `4c7b3b0` 15:24 (dev.yaml +61/−…), `4cb7a07` 16:11, `ef3a532` 20:58 (dev.yaml +122) |
| `-002` | 2026-09-02 13:22 EDT | `4cb7a07` 16:11 (release.yaml +33), `ef3a532` 20:58 (release.yaml +226) |
| `-003` | 2026-09-02 18:40 EDT | `ef3a532` 20:58 (deleted both its scripts and their pytest) |

Sources: `state/events.jsonl` status events; `git log --format='%h %ai'` on the range;
`git show --stat 4c7b3b0 4cb7a07 ef3a532`.

Three stories were rewritten — one of them losing 514 lines of its own delivered code — with **no
status transition back to `in-progress` and no event recorded**. The story documents carry the
narrative (`E008-S01-003.md:208-235`, ADR-0011:105-113), so the record is not lost; but a reader of
`state/` alone would conclude story 001 was finished at 12:30 and untouched thereafter, which is
false. `actual` hours were sampled at the `done` mark and therefore **exclude every post-`done`
rework hour** — which means the 2.0× / 3.0× overrun figures above are an *under*-count.

### F-A3 — Story 003 was marked `done` 79 minutes before its code was committed

`status → done` at `2026-09-02T22:40:41Z`; `ea6b1e4` committed at `2026-09-02T23:59:36Z`, with
`dispatch_close` 22 seconds earlier. The git status snapshot taken at the start of this
retrospective session showed `E008-S01-003.yaml.lock` untracked in the tree alongside uncommitted
modifications to `scripts/stable_tags.py`, `tests/test_stable_tags.py` and untracked
`scripts/finalizer_gate.py` — the signature of a run interrupted between verification and commit.
The lock is gone from the tree now; the delivery is committed and the suite is green.

**The consequence is the one that matters:** `done` in state is not tied to a commit. For a window
of 79 minutes, `E008-S01-003.yaml` asserted `tests_passing: true` with `completion_evidence` naming
five green commands, over a working tree whose content existed nowhere but that tree. This is the
same failure shape as the E007 repository loss, in miniature and survived.

### F-A4 — A previous retrospective's learning recurred, because it was prose

Epic 6's retrospective records, verbatim: *"Never assume a GitHub Action's current major version —
checking the actual releases page surfaced that four actions were TWO majors behind… and confirmed
the one case where a major bump needed an input-name compatibility check before applying."*
(`epic-006/sprint-01/closure/retrospective.md:45-49`).

Epic 8 hit both halves again. Story 003's implementation record
(`E008-S01-003.md:155-168`) reports that `git-action-tag-floating-version@v1` takes **camelCase**
inputs (`updateMinor`, `ignorePrerelease`), while the story *and ADR-0006* both carried the
hyphenated spelling — *"not an input at all; the action would have fallen back to
`updateMinor: false` and the `vMAJOR.MINOR` alias would have silently never moved."* The same story
also found the action is `using: node20`, not node24 as ADR-0006 recorded. Then `ef3a532` moved the
alias action `@v1`→`@v2`.

Two majors behind, and an input-name incompatibility, caught by reading `action.yml` — exactly what
epic 6 wrote down. The learning changed no artifact and enforced nothing, so it prevented nothing.
This is global rule §3 with two years of the project's own evidence behind it.

### F-A5 — `forge_coordinates` is the clearest case in the repo of a constraint accepted untested

The chain is fully traceable and worth stating plainly, because it began in a *quality* gate:

1. Gate 1 **F9** (`arch-gate-review.md`, F9 row) ruled: *"Put both validators in `scripts/` … as
   Python functions with pytest cases — `urllib.parse` for the coordinate rule … Neither is
   unit-testable inside a `run:` block, so the guard degenerates into grepping the workflow for its
   own regex."* Cited global rule §1 (never hand-roll URL matching) and Core §4 (testability).
2. Story 001 implemented it (`E008-S01-001.md:135`, "Validators are Python with tests, not regexes
   in `run:` blocks (F9)"): `scripts/forge_coordinates.py` (235 lines) + a composite action (60) +
   `tests/test_forge_coordinates.py` (240) = **535 lines**, all committed and green.
3. `4c7b3b0` deleted every one of them. The surviving test says why, and it executes the real `run:`
   body to prove it: *"Every coordinate is a projection of `github.server_url` and
   `github.repository`, so there is **no operator-supplied value to validate** — the composite
   action and the module it called were 535 lines producing six template expressions."*
   Source: `tests/ci/test_workflow_contracts.py:1437-1451`.

Neither the gate nor the orchestrator asked the question global rule §2 exists to force: *what is
actually being validated, and is it hard?* Six template expressions over action context are not.
The 40 lines of URL validation guarded `FORGE_REGISTRY`, an override that had never been set — and
was retired with the module. **F9 is a gate finding that cost 535 lines and produced nothing**, and
it was raised under a rule about avoiding exactly that kind of cost.

The follow-on ruling ("no Python in the publication path") then removed `stable_tags.py` (301) and
`finalizer_gate.py` (213) with **613 lines of their pytest** (424 + 189), on the precedent
`forge_coordinates` set (ADR-0011:105-113). That second removal is a different and better trade:
`jq` in a `run:` step, with the properties re-proven by *executing the real `run:` body* under a
real git fixture — which is stronger evidence than the deleted unit tests provided, since a unit
test of a module the workflow might stop calling proves nothing about the workflow.

**Net for the sprint: 1,362 lines written, reviewed, tested, committed, and then deleted.**

### F-A6 — Stale references survived the deletions

Live artifacts still name modules that no longer exist:

- `tests/ci/test_workflow_contracts.py:2336` — a live test's docstring states its planted proof as
  *"dropping the `object_type == "tag"` filter from `stable_tags.annotated_tags` makes the
  lightweight case pass."* That module was deleted in `ef3a532`. The guard itself is fine (it
  executes the real `run:` body), but its stated proof-of-reach is now unperformable, so a reader
  cannot re-verify the claim the docstring makes.
- `state/issues.yaml` **BL-E008-003** describes the defect as *"passes `DEFAULT_BRANCH_REF:
  origin/main` to `scripts/stable_tags.py --reachable-from`"* and **BL-E008-006** as *"the finalizer
  gate's `PUBLISHER_RESULTS`… `finalizer_gate.evaluate` rejects a mismatched set."* Both scripts are
  gone. **The underlying issues are still real** — `release.yaml:131` still hard-pins
  `DEFAULT_BRANCH_REF: origin/main`, and the destination-key vocabulary is still hand-written — but
  whoever picks these up will look for files that were deleted.

`tests/ci/test_workflow_contracts.py:1444` and `docs/adr/0011:107-108` also name the deleted files;
those are correct, because both are *recording the deletion*.

### F-A7 — A live guard's docstring describes a world that ended this sprint

`test_any_push_triggered_workflow_verifies_before_it_ships`
(`tests/ci/test_workflow_contracts.py:479-489`) still reads: *"no workflow reacts to push right now
— Epic 8's `dev.yaml` closes that… Passes vacuously today and bites the moment a push workflow
reappears."* `dev.yaml` reacts to `push: branches: [main]` (`.github/workflows/dev.yaml:13-16`), so
the test no longer passes vacuously; `BL-E008-001` is marked `resolved` on exactly that basis. The
body was correctly widened past `push` alone (gate-2 **N5**) and carries an accurate inline comment
at `:495-497`. Only the docstring is behind — but it is the docstring that tells the next reader
whether this guard is load-bearing, and it says it is not.

### F-A8 — The two guards restored in story 004 were both lost the same way, and neither loss was detected by a check

`df6e5ed` restored `test_publication_contract_extra_and_dev_constraints_agree` and
`test_the_runtime_image_dependency_set_excludes_ci_only_tooling`
(`tests/ci/test_publication_contract.py:509,541`, +54 lines), and the Dependabot/`ARG BASE_IMAGE`
reach half at `tests/ci/test_workflow_contracts.py:1099-1148`. That guard's own comment records the
history: *"Dependabot resolves `FROM $VAR` only through an ARG default, so an undefaulted
`ARG BASE_IMAGE` leaves the watched directory unupdatable while this config still reports coverage.
**That exact regression reached main once already.**"*

Both were separated from the fixes they prove by the E007 repository loss, and both were
rediscovered by someone noticing — not by any mechanism. There is still no check that would notice
a third occurrence. On the positive side, the restored guard parses with `dockerfile-parse` rather
than a hand-rolled scanner, with only the Dependabot-specific ARG resolution local — global rule §1
applied correctly, and the same choice `markdown-it-py` got in the runbook checker (review 004
MEDIUM-3).

### Review-scope narrowing (recorded)

Phase 2's `bmad-review` pass over the epic diff was **not re-run**, for two reasons, both recorded
rather than assumed: (a) four full adversarial reviews already exist for this diff, one per story,
totalling 53 findings with per-finding dispositions in the story documents — re-deriving them would
produce a fourth copy of the same list; and (b) `events.jsonl` shows the orchestrator dispatched
`bmad-review-adversarial-general` and `l3io-sec-redteam` **in parallel with this retrospective** at
`2026-09-03T02:30:10Z`, so a fresh adversarial pass is in flight from a sibling agent. The
cross-story boundary analysis the skill asks for — the part no single story session could see — was
performed here directly over the diff and the artifact set, and is what F-A1 through F-A8 are.

## Behavior verification

**Runtime behavior was not exercised, and could not be.** Everything this sprint delivered runs only
inside a forge's Actions runtime; there are no workflow runs to observe from this working copy, and
`BL-E008-001`'s own resolution note records that `v*` tag pushes were unverified until `release.yaml`
landed. Specifically not exercised: any `dev.yaml` or `release.yaml` run; multi-platform image
publication to any registry; the forge Release creation; alias finalization; the failed-jobs-only
recovery path documented in `docs/operational.md`.

**Docker Hub has never been configured for this repository** (`BL-E008-004`, status `resolved`:
"the variable and its secrets are documented in `docs/operational.md` but have never been set… so
the Docker Hub destination is untested end to end"). The item is marked resolved on the basis that
the fail-closed *design* is settled, not that the destination works.

**The strongest evidence that does exist** is better than static reading and worth crediting: the
contract suite executes the real `run:` bodies of the guard, tag and finalizer steps against a real
git fixture (`_run_step`, `tagged_repository`, e.g. `tests/ci/test_workflow_contracts.py:2330-2345`,
`:1437+`), and the sprint planted **57 violations** across stories 003 and 004 (33 and 24 by their
own records), every one confirmed to fire. That tests the logic. It does not test the runner.

Verified locally for this report: `poetry run pytest --collect-only` → **333 collected** at `HEAD`;
the same command in a detached worktree at `72feefb^` → **150 collected**;
`grep -c "def test_" tests/ci/test_workflow_contracts.py` → **124** at HEAD, **34** at `72feefb^`.

*Minor evidence discrepancy:* `E008-S01-004.md:200` reports "331 passed"; the tree at `HEAD` collects
333. Two tests' worth of drift between the story's final run and the commit; not material, noted so
it is not mistaken for a regression.

## Previous-retro follow-through

**There is no epic-7 retrospective.** `epic-007/` contains only `epic-closure/closure-report.md`,
which states at line 24 that *"what is genuinely lost: the sprint retrospective, the arch-review
report itself…"* — the retrospective was among the casualties of the repository loss. There are
therefore no epic-7 action items to check, and **no `--set-action-status` transitions to propose**.

The nearest prior record is epic 6's retrospective, whose action-item follow-through is covered in
**F-A4**: its learning about action major versions and input-name compatibility recurred in full in
this sprint. It was recorded as prose, with no artifact or guard attached, and it did not hold.

## Action items

None of these are applied — the orchestrator and the maintainer own execution.

| # | Item | Class | Owner | Notes |
|---|---|---|---|---|
| A1 | Add a meta-guard over the contract suite: for each guard, assert its scope set is derived (from a glob, a parse, or a consumer) rather than from a module-level literal tuple; where a literal is genuinely correct, require an inline justification the guard checks for | fix — proposed | maintainer | The single highest-value item. F-A1: this class produced 6 of gate 1's 20 blocking findings, 5 of gate 2's 14 planted-and-passed probes, and 8 story-review findings, and recurred *after* being named twenty times. Global rule §4 is currently enforced only by reviewer attention |
| A2 | Correct `BL-E008-003` and `BL-E008-006` descriptions to name the surviving `run:` steps instead of the deleted `scripts/stable_tags.py` and `finalizer_gate.evaluate` | fix — proposed | orchestrator | F-A6. Both defects are still live in the tree; only the pointers are wrong |
| A3 | Update the docstring at `tests/ci/test_workflow_contracts.py:2336` to name the real plant (the `object_type == "tag"` filter in `release.yaml`'s `tag` step), and the one at `:479-489` to state that `dev.yaml` now makes it non-vacuous | fix — proposed | maintainer | F-A6/F-A7. Both are one-line edits; both currently mislead about whether the guard bites |
| A4 | Make a story's `done` transition require a commit: record the commit SHA in `completion_evidence`, and refuse the transition on a dirty tree or absent commit | process | orchestrator | F-A3. `done` preceded the commit by 79 minutes with a stale `.yaml.lock` in the tree; this is the E007 loss shape at small scale |
| A5 | Give the state machine a transition for post-`done` rework — reopen, or a `rework` event — and re-sample `actual` after it | process | orchestrator | F-A2. Three stories were rewritten after `done` with no event; the recorded 2.0×/3.0× overrun excludes all of that work |
| A6 | Before an architecture gate mandates a mechanism (a module, a validator, a script), require it to state what the mechanism validates and why that is hard | process | arch-review | F-A5. F9 mandated a validator for six template expressions and a never-set override variable; 535 lines were written and deleted. Global rule §2's three questions, applied to the gate's own findings |
| A7 | Attach every retrospective learning to an artifact or a guard, or record explicitly that it is unenforced | process | orchestrator | F-A4. Epic 6's action-version learning was prose, and recurred verbatim in epic 8 |
| A8 | Add a check that a fix and the guard proving it cannot be separated — e.g. assert every guard in `tests/ci/` names a live file or symbol | fix — proposed | maintainer | F-A8. Two guards were lost with E007 and rediscovered by accident; there is still no mechanism that would catch a third |
| A9 | Re-estimate epic 9 with this sprint's ratios (2.0× man-hours, 3.0× elapsed, both under-counts) rather than the pre-sprint model | process | orchestrator | The four stories' `estimate` blocks all used `fix_factor: 1.25` and `confidence: medium`; the observed factor is materially higher |
| A10 | Set `DOCKERHUB_REPOSITORY` + credentials and run one end-to-end publication, or record that the destination stays off | fix — proposed | maintainer | `BL-E008-004` is `resolved` on design grounds while the destination has never been exercised; the runbook documents a path nobody has walked |

## Acceptance verdict

**accepted-with-open-items.** Criteria were **declared** — each story carries an Acceptance Criteria
section, a Definition of Done and named test anchors, and `epic.yaml` declares the epic goal
("Publish verified development and stable artifacts through normal destination actions, then advance
aliases only after required jobs succeed").

Evidence for the call:

- All four stories are `status: done`; `pending_stories` is empty, so nothing forces the machine
  verdict to **rejected**.
- Each story's `completion_evidence` records `tests_passing: true` with named commands and exit
  codes; independently reconfirmed here — 333 collected at `HEAD`, 124 contract guards.
- Both halves of the epic goal are implemented and guarded: `dev.yaml` and `release.yaml` publish
  through vendor destination actions with no Python in the path, and aliases move only behind
  registered finalizers whose refusals are asserted to *precede* every write
  (`test_every_refusal_a_finalizer_makes_precedes_everything_it_writes`, review 003 H1).
- Gate 2's BLOCKER **N1** and its E008-scoped MAJORs were addressed in the stories that followed
  (F16's tag-race acceptance is recorded at `E008-S01-001.md:167`); the carried findings F18/F19/F20
  are E009-scoped and travel with that epic, not as E008 carry-over.

**Open items, which is why this is not plain "accepted":** three deferred LOW findings
(`BL-E008-002`, `-003`, `-006`), one upstream security item (`BL-E008-005`, Medium, not exploitable
here because validation precedes use), the Docker Hub destination never exercised (`BL-E008-004`,
A10), and the fact that **no part of this pipeline has run on a real runner** — the epic's entire
value is asserted by contract tests that execute `run:` bodies, not by a publication that happened.

**Carry-over story scope: 0.** Nothing was left unfinished or deliberately deferred at story
granularity; the deferrals above are backlog items and closure follow-ups, counted separately.

## Open questions

1. **Is a rule the reviewers keep having to enforce a rule at all?** Global rule §4 was cited by
   name in twenty findings and violated again in guards written afterwards. Either A1's meta-guard
   lands, or the honest move is to record that guard scope is reviewed by humans and not enforced.
2. **Should the "no Python in the publication path" ruling be an ADR?** It has now cost 1,362 lines
   across two removals and set a precedent ADR-0011 cites explicitly, but it lives as a maintainer
   instruction, not a recorded decision with a revisit condition. Global rule §1's escape hatch runs
   in this direction too: a ruling that deletes tested code deserves the same record as one that
   writes it.
3. **Does the sprint's cost model mean anything without token actuals?** Everything ran under
   `runtime: other`. `epic.yaml` estimated 1,585–1,801k tokens and $6.54–7.43 against nothing.
   Either the runtime starts reporting, or the token/cost fields should be dropped from estimates
   rather than carried as unfalsifiable numbers.

## Assumptions

Recorded because this was a headless run and no user confirmed any of it.

1. **Epic and sprint were taken from the invocation** (`epic_key: E008`, `sprint: S01`), not
   auto-detected — the stable `-H <epic>` orchestrator path.
2. **`sprint_status.py detect-epic` was not run.** This project has no
   `implementation-artifacts/sprint-status.yaml`; state is sharded under `state/active/epic-008/`.
   The completeness gate was performed against the four per-story YAMLs instead, all four
   `status: done`, so `pending_stories` is empty. Assumed equivalent; it is the same source of
   truth, but not the script-backed check the skill specifies.
3. **Verdict `accepted-with-open-items` was rendered on evidence alone**, with no human decision.
   No unfinished story forced **rejected**. A human override supersedes this.
4. **All ten action items are proposals.** Nothing was applied; no state was mutated; no commit was
   made. Per the dispatch constraints, `set-status`, `set-actual` and every story/sprint/epic YAML
   edit remain the orchestrator's.
5. **No `--set-action-status` transitions are proposed**, because epic 7 has no retrospective to
   carry action items from — it was lost with the repository (`epic-007/epic-closure/closure-report.md:24`).
6. **Phase 2's `bmad-review` invocation was deliberately not re-run**; the narrowing and its two
   reasons are recorded above under "Review-scope narrowing".
7. **Phase 3 (team discussion) was skipped**, as headless runs never open it.
8. **Runtime behavior was not exercised** and no substitute was invented; see "Behavior verification".
