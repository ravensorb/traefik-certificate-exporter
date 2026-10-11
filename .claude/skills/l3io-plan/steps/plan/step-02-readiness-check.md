# Step 02: Readiness Check

Communicate all responses in `{communication_language}`.

Run after step-01-classify-work. Validates every story in scope before planning proceeds.
Bind `{readiness}` to the gate result before loading the next step.

---

## 0. Pre-scan: artifact-only story detection

Before reading state, check whether the artifact tree holds story `.md` files that have
no corresponding state YAML. Runs for every `{work_type}`.

```bash
find {implementation_artifacts}/epic-*/sprint-*/stories -name 'E*.md' 2>/dev/null | sort
```

For each `.md` file found at path
`{implementation_artifacts}/epic-{nnn}/sprint-{nn}/stories/{story_key}.md`:

Check whether a state YAML exists for that key anywhere in the state tree:

```bash
find {pm_state_root}/active {pm_state_root}/planned {pm_state_root}/archived \
  -name "{story_key}.yaml" 2>/dev/null | head -1
```

If the `find` prints nothing, the story has an artifact but no state node — collect it as
an **artifact-only** story.

If **any artifact-only stories are found**, halt immediately with `{readiness}` = `red`:

```
🔴 Readiness check FAILED — {count} story artifact(s) have no state node.

These stories exist as .md files in the artifact tree but have no corresponding
state YAML under {pm_state_root}/. l3io-plan reads state only, so these stories
are invisible to planning, estimation, and execution.

Artifact-only stories:
{list each: {implementation_artifacts}/epic-{nnn}/sprint-{nn}/stories/{story_key}.md}

Fix: run /l3io-doctor bootstrap-state to create state nodes from your artifact
files. This is a one-time step for projects whose stories were created outside l3io-pm
(e.g. via the legacy `bmad-create-story` workflow, without going through l3io-plan).
```

BLOCKED: artifact-only stories detected — run `/l3io-doctor bootstrap-state` first.

If no artifact-only stories are found (or no `.md` files exist at all), continue to §1.

---

## 1. Collect stories in scope

Read all stories from:
- All epics under `{pm_state_root}/active/` with `status: in-progress`
- All epics under `{pm_state_root}/planned/` with `status: backlog`

For each epic, list its sprint directories and each sprint's story `.yaml` files (excluding
`sprint.yaml`) to enumerate stories — or use `uv run {pm_status} show --state-root {pm_state_root} --epic {epic_key}` for a quick status roll-up.

For each story, record: `key`, `classification`, `status`, `estimate` (present/absent),
`depends_on`, and whether it is assigned to a sprint.

### 1.1 Guard: there must be something to plan

**Check the scope set is non-empty before validating anything in it.** Every check in §2 is
stated per story, so over an empty set all of them hold — no Red finding, no Amber finding — and
§4's `All Green → green` is reached **vacuously**. A run with nothing in it would otherwise
report green readiness, write a snapshot of 0 epics across 0 phases, and tell the user to run
`/l3io-execute`, which is the one piece of advice that cannot possibly be right.

This guard is **ours and not the external readiness checker's**, for three reasons that are
worth keeping here: the legacy `bmad-check-implementation-readiness` is invoked *per story*, so
with zero stories it is invoked zero times and structurally cannot report their absence;
`bmad-sprint-planning` reads BMad's own scope, not `{pm_state_root}`; and §3 is skipped entirely
when neither resolves, which would make the guard disappear on exactly the installs least likely
to notice. §1 computes the set, so §1 is where its emptiness is known.

If **no epics** are in scope — nothing under `active/` with `status: in-progress`, nothing under
`planned/` with `status: backlog` — halt with `{readiness}` = `red`:

```
🔴 Readiness check FAILED — there is nothing to plan.

No epics are in scope: {pm_state_root}/active/ holds no epic with status in-progress,
and {pm_state_root}/planned/ holds none with status backlog.

Fix: create epics and break them into stories first. If you already have epic or story
documents in {implementation_artifacts}, they have no state nodes yet — run
/l3io-doctor bootstrap-state to create them.
```

If epics are in scope but **together they hold zero stories**, halt with `{readiness}` = `red`
and **name them** — an epic that was declared and never decomposed is the common way to reach
this, and the user needs to know which:

```
🔴 Readiness check FAILED — {epic_count} epic(s) in scope hold no stories.

{list each epic key and title}

An epic with no stories contributes nothing to a plan: it has no estimate to roll up and
no work to order. Break these down into stories first.
```

If **some** epics hold stories and others hold none, do not halt — the plan is still
producible. Record one **Amber** finding per empty epic, so it appears in §5's report and
carries into `{readiness}`. An empty epic otherwise rolls up as a zero-cost epic in the
estimate and reads as cheap rather than as undecomposed.

## 2. Run validation checks

For each story, evaluate the following checks:

| Check | Green | Amber | Red |
|-------|-------|-------|-----|
| Classification | `classification` is `simple`, `standard`, or `complex` | — | Missing or unrecognized value |
| Technical ACs | If `{work_type}` is CODE, CONFIG or MIXED: story file exists, carries `## Technical acceptance criteria`, and **every one of the six dimensions** below is present and either filled or marked `N/A — <reason>` | **Any applicable dimension missing or empty**, or the story document does not exist yet | Story document exists but carries no `## Technical acceptance criteria` heading at all |
| Business ACs | `## Business acceptance criteria` is present with a non-empty `### Outcome` | Section absent, or `### Outcome` empty | — |
| Estimate block | `estimate` block present with at least `man_hours` or `man_hours_low` | **Absent** — `steps/shared/step-estimate.md` writes it later in this same run | — |
| `depends_on` validity | All referenced keys exist in scope and are not `done` | — | Any key missing from any state file, or a cycle detected |
| Sprint assignment | Story is assigned to a named sprint in its epic | — | Orphaned story (not in any sprint) |

Technical ACs check applies when `{work_type}` is CODE, CONFIG or MIXED. For DOCS only, skip this check for all stories. It must run for CONFIG: step 03 elaborates only the stories this check grades Amber, so skipping CONFIG here would leave `{readiness}` green and elaborate nothing for an infrastructure epic.

**The six dimensions, and why this check must name all six.** They are the headings step 03's
enricher writes, and the canonical reference is `references/ac-dimensions.md`, which both this
skill and `l3io-execute` carry so the two cannot drift:

| # | `###` heading | Covers |
|---|---|---|
| 1 | Interface contracts | signatures, data model, what callers see |
| 2 | Error and edge case handling | what fails, how, and what the caller gets |
| 3 | Observability requirements | logging, metrics, tracing the change must emit |
| 4 | Security considerations | auth, validation, data handling |
| 5 | Testability approach | test entry points and mock boundaries |
| 6 | Existing-library check | which library or platform capability covers this, or why custom code is warranted |

This check previously named three of them — interfaces, data model, error handling — while the
elaborator four steps later wrote all six and `l3io-execute`'s story gate **blocks**
`ready-for-dev` on any applicable dimension left unfilled. The enricher and the checker in one
skill disagreed about what "ready" means, and the stricter of the two was the one that did not
gate. The effect was not a missed warning: a thin story was graded Amber, estimated, placed on
the critical path, and only then blocked at execution — so the schedule had been built around
work that could not start. Grading the same six here makes that block predictable at plan time
and tells step 03 exactly which dimensions to fill.

**A dimension marked `N/A — <reason>` is Green, not Amber.** "Does not apply, and here is why"
is a filled dimension; an unfilled one is a gap. Omitting the heading entirely is never
acceptable — that is indistinguishable from not having considered it.

**Both AC rows are Amber, never Red, for the reason the next two notes give**: step 03 runs
immediately after and exists to close exactly these gaps. Red would halt the run before the
step that fixes it.

**Spec pointers are deliberately NOT checked here.** In plan mode `Spec: none — <reason>` is the
expected answer for every applicable dimension: `spec_alignment` and `spec_paths` are
`l3io-execute` keys, and `l3io-plan` passes no spec index (see `step-03-story-elaboration.md`).
Running `spec-align.py check-pointers` at plan time would fail every story by design, and
`l3io-plan` does not carry that script in any case. Pointer resolution is `l3io-execute`'s gate,
where the index exists.

**An absent story document is Amber, not Red, deliberately.** Red halts this step with `BLOCKED` and forbids loading the next one (§6) — and the next one, step 03, is exactly where §4 says "if the file does not yet exist at the given path, create it first" before enriching it. Grading a missing document Red therefore blocked the only step that could produce it, and left that create-it-first branch unreachable by any input: Amber requires a file to exist, so no story could ever arrive at it. Amber is the grade for a gap elaboration closes, and a missing document is one. A document that exists but carries no AC section stays Red — that is a story someone wrote and left empty, which is a content decision rather than a missing artifact.

**A missing estimate block is Amber for the same reason.** The full-plan router loads `steps/shared/step-estimate.md` four steps after this one, so Red here halted the run before the step that writes the estimates it was demanding — the story-document case above, one row down. Nothing about an absent estimate needs a human: this step reports the gap, and the estimate step fills it before the plan is written. The row therefore has no Red. Two things kept this rarer than it looks, and neither makes it safe: `/l3io-plan estimate` loads the estimate step alone and bypasses readiness entirely, and `promote-issue` writes a calibrated estimate block when it creates a story, so stories that arrive through backlog intake never lacked one. A story created any other way did.

## 3. BMad readiness integration

Resolve the readiness checker. The legacy `bmad-check-implementation-readiness` skill was folded into `bmad-sprint-planning` at 6.12.0.
The old name is probed first: where it exists, this is an older install and `intent=readiness`
may not be understood.

```bash
for n in bmad-check-implementation-readiness bmad-sprint-planning; do
  ls {project-root}/.claude/skills/$n/SKILL.md 2>/dev/null \
    || ls {project-root}/.claude/commands/$n.md 2>/dev/null \
    || ls ~/.claude/skills/$n/SKILL.md 2>/dev/null \
    || ls ~/.claude/commands/$n.md 2>/dev/null
done | head -1
```

Bind `{readiness_checker}` to whichever name resolved; an empty result leaves it unbound.

- `{readiness_checker}` = the legacy `bmad-check-implementation-readiness` → invoke it per story with the
  story file path, as before.
- `{readiness_checker}` = `bmad-sprint-planning` → invoke it once with `intent=readiness`; it runs its own
  readiness gate and returns `gate` as `PASS`, `CONCERNS`, or `FAIL`. Map `CONCERNS` → amber and
  `FAIL` → red. It is headless-aware ("When invoked headless, do not ask").
- Neither → skip this section; `{readiness}` is decided by §1–§2 alone.

Fold "not ready" findings into the gate:
- Fewer than half the stories flagged as not ready → amber
- Half or more flagged → red

## 4. Compute gate result

- Any Red finding on any story → `{readiness}` = `red`
- Any Amber finding, no Red → `{readiness}` = `amber`
- All Green **over a non-empty scope set** → `{readiness}` = `green`

**Green requires stories to have been checked, not merely no failures to have been found.**
§1.1 already halts on an empty set, so this restatement is belt and braces — but the two
clauses fail independently, and the one that is easy to delete by accident is the guard. Every
check in §2 is universally quantified over the stories, so without the qualifier here, deleting
§1.1 would silently restore a green verdict over nothing rather than producing an error.

## 5. Write readiness-report.md

Write `{planning_artifacts}/readiness-report.md`:

```markdown
# Readiness Report

Generated: {timestamp}
Gate result: {readiness}
Stories checked: {total_story_count}

## Findings

| Node | Check | Result | Detail |
|-------|-------|--------|--------|
| E001-S01-001 | Technical ACs | 🟡 Amber | Functional ACs only — no interface specs |
| E002-S01-003 | Estimate | 🔴 Red | Missing estimate block |
| E001-S02-001 | depends_on | 🟢 Green | — |
| E004 | Decomposition | 🟡 Amber | Epic holds no stories — contributes nothing to the plan |

The first column is a **node** key, not only a story key: §1.1's empty-epic finding is recorded
against the epic, because that is the node the user has to act on.

## Summary

- Green: {count}
- Amber: {count}
- Red: {count}
```

## 6. Apply gate outcome

**`{readiness}` = red:**
```
🔴 Readiness check FAILED — {count} blocking issue(s) found.
See {planning_artifacts}/readiness-report.md for details.
Resolve all Red findings before running /l3io-plan again.
```
BLOCKED: readiness gate — red. Do not load the next step.

**`{readiness}` = amber:**
```
🟡 Readiness check passed with warnings — {count} non-blocking issue(s).
Estimates for affected stories will be marked low-confidence.
See {planning_artifacts}/readiness-report.md for details.
Continuing with plan...
```

**`{readiness}` = green:**
```
✅ Readiness check passed — all {count} stories ready.
```

## 7. Output status line

```
Step 02 complete — readiness: {readiness}, stories: {total_story_count}, gaps: {amber_count} amber / {red_count} red
```
