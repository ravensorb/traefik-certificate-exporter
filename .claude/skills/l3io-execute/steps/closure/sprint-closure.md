# Sprint Closure Workflow

Communicate all responses in `{communication_language}`.

This file is loaded by step-04-sprint-closure.md. Run each phase; skip phases listed in
`{skip_phases}`.

## Phase gating

The phase matrix lives in `steps/shared/step-01-classify-work.md` §4 and is the single source
of truth. It bound `{skip_phases}`; run every phase below except those it names. This file
deliberately carries no copy of that table — the duplicate it used to hold is what let the two
drift.

Note for DOCS work: UX review is skipped. Documentation does not get a UX review pass.

## Dispatch rule for every spawn in this file

Every phase below that spawns or invokes a subagent — retrospective, adversarial review,
red team, UX, arch drift, and any fix-loop re-dispatch — brackets it with
`dispatch --event open` / `--event close`, same `--agent <name> --epic {epic_key} --sprint {sprint_num}
--session-id {session_id}` identity on both, closed on **every** exit path.

Include `{agent_contract}` (verbatim — see `steps/shared/step-00-digest.md`) in every spawn prompt.
These are `bmad-*` and `l3io-*` agents that load no part of the activation digest; without it
they have no instruction to stop rather than wait.

Attribution is unchanged by the bracket: closure phases are **closure** spend, added on top of
the children's sum in the sprint's own `actual` — never a child's `actual` and never
`orchestration` (`references/metrics-contract.md` §6). The bracket here buys stall detection,
not a change of bucket.

## 1. Retrospective

Spawn `bmad-retrospective` (or inline if not installed):
- Summarize stories completed, velocity vs estimate, blockers encountered
- Produce `retrospective_summary` (2–3 sentences) and `carry_over_count`
- Write report to `{sprint_root}/closure/retrospective.md`

## 2–3. Clean release review and adversarial analysis

These are two phases with independent gating, run by **one agent** whenever both are in
scope. They are the same reviewer (`{adversarial_reviewer}`) over the same changed
files, and a reviewer's cost is dominated by reading the project — inviting it twice paid
that read twice for one pass's worth of context.

**Check each phase's gating separately; they differ.** Per the matrix in
`steps/shared/step-01-classify-work.md` §4, CODE, MIXED and CONFIG all run both
phases; only DOCS skips them. The merge is still conditional on `{skip_phases}` rather than
unconditional — if the matrix ever suppresses one phase for a work type, collapsing them would
silently extend the other's coverage to it:

| In `{skip_phases}` | Do this |
|---|---|
| neither | **one** invocation, both scopes (CODE, MIXED and CONFIG) |
| adversarial only | one invocation, `clean-release` scope alone (no work type does this today; the matrix may add one) |
| both | run nothing (DOCS) |

**Scope every reviewer to the diff and named sections — never the repository.** Pass the
changed files (or the diff itself) plus the *specific* spec/standard sections that apply, by
path and section number. Never point a reviewer at the project and let it decide what to
read: a reviewer that loads the corpus pays a full `cache_write` over it before its first
thought, and then re-reads that prefix on every turn it takes. Scoped this way a reviewer's
spend measures at roughly **3.4% of a story's tokens**; unscoped it is a multiple of the work
under review. If a reviewer says it lacks context, name the additional section — do not widen
it to the repository.

**Resolve the reviewer.** `bmad-review-adversarial-general` merged into `bmad-review` at 6.12.0,
where its behavior is the `adversarial` lens.

```bash
ls {project-root}/.claude/skills/bmad-review/SKILL.md 2>/dev/null \
  || ls {project-root}/.claude/commands/bmad-review.md 2>/dev/null \
  || ls ~/.claude/skills/bmad-review/SKILL.md 2>/dev/null \
  || ls ~/.claude/commands/bmad-review.md 2>/dev/null
```

A path printed → `{adversarial_reviewer}` = `bmad-review`, invoked as
`skill:bmad-review lenses=adversarial`, with the clean-release checklist passed as
`also_consider` (a documented `bmad-review` input). Nothing printed → probe
the legacy `bmad-review-adversarial-general` the same four ways and invoke it with both scopes exactly as before. <!-- l3io-deprecation-exempt: phase-3 — fallback only when bmad-review is absent; the whole preference-probe is retired in Phase 3, see docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md §5 Phase 3 -->
Neither present → skip the phase and say so in the phase output, so a skipped review is
never mistaken for a passed one.

Invoke `{adversarial_reviewer}` with **the sprint's diff** and the scopes that
survived that check:

- scope `clean-release` — dead code, commented-out code, debug artifacts, TODO markers,
  and any secrets or credentials in changed files.
- scope `adversarial` — threat-model the sprint's changes.

Return findings **tagged by which scope raised them**, so triage stays per phase and the
closure report can still say which phases ran:

- `clean-release` CRITICAL/HIGH: fix immediately (re-invoke dev subagent). MEDIUM/LOW: defer to issues.
- `adversarial` CRITICAL/HIGH: block closure, fix loop (max `{max_fix_iterations}` iterations).
  MEDIUM: fix in place. LOW: defer. Write both scopes' findings, each with its ID and scope
  tag, to `{sprint_root}/closure/adversarial-review.md`.

## 4. Red team (skip if in skip_phases)

If `l3io-sec-redteam` is installed:
```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-sec[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```
**Redteam is not scoped like the reviewers above — give it a starting set, not a fence.**
The diff-scoping rule in §2–3 exists because a diff *is* a reviewer's whole input; redteam's
own method (`l3io-sec-redteam/references/scope-mapping.md`, that agent's own reference — not
this skill's) is different by design: it builds a
surface map — entry points, trust boundaries, data flows, auth checkpoints, persistent
state — "from what's actually implemented, not from documentation assumptions," and states
that "a scope with no entry points or no trust boundaries is incomplete — expand until the
picture is coherent." A diff cannot show an undocumented endpoint, an implicit trust
relationship, or where a changed function sits relative to an auth checkpoint. Fencing it to
the diff, the way a code reviewer is fenced, would forbid the one thing its method requires.

Spawn `l3io-sec-redteam` per its documented orchestrator-invocation contract (`SKILL.md`
"On Activation" step 1, orchestrator invocation — explicit scope, artifact paths, and output
path). Pass:

- **Scope statement**: sprint-level security analysis, epic `{epic_key}` sprint
  `{sprint_num}`.
- **Seed artifacts** (a starting set, not a fence): the sprint's diff, plus each in-scope
  story's `Files in scope` / File List — `scope-mapping.md` names story File Lists as what it
  traces from when scope is vague.
- **Explicit permission to widen**: it may read beyond the seeds to trace entry points, trust
  boundaries, data flows, and auth checkpoints the diff touches or sits near — that is its
  method, not a workaround, and is not subject to the "never the repository" rule above.
- **Output path**: `{sprint_root}/closure/redteam-report.md`.

Cost discipline still applies, in the form that fits an agent that must explore: start from
the seed artifacts, widen only with a reason, and **report what it widened to and why** in
the findings report. Accountability, not prohibition.

CRITICAL/HIGH findings: block until resolved. LOW: defer to issues file.

## 5. UX review (skip if in skip_phases)

If a UX reviewer is installed and `{ui_facing_stories}` (from the execution context; empty if absent — do not re-derive) names a story in this sprint:
```bash
for n in bmad-ux-review bmad-ux; do
  ls {project-root}/.claude/skills/$n/SKILL.md 2>/dev/null \
    || ls {project-root}/.claude/commands/$n.md 2>/dev/null \
    || ls ~/.claude/skills/$n/SKILL.md 2>/dev/null \
    || ls ~/.claude/commands/$n.md 2>/dev/null
done | head -1
```
Bind `{ux_reviewer}` to whichever resolved — the legacy `bmad-ux-review` preferred because it is
built for review, `bmad-ux` used via its **Reviewer Gate** (opt-in, lens-selectable) when it is all that
exists. Empty result → skip the phase and say so in the phase output, so a skipped review is never mistaken for a passed one.
If present: invoke with story files that have UX acceptance criteria.
HIGH: fix. LOW/MEDIUM: defer. Output path: `{sprint_root}/closure/ux-review.md`.

## 6. Sprint architectural drift review (skip if in skip_phases)

If `l3io-arch-review` is installed: invoke Mode B (architectural review) on this sprint's
stories and **diff**, plus the ADRs and standard sections they bear on, by path — not the
repository (see §2–3). List the epic's ADRs with `{spec_align} adrs --epic {epic_key}`. Output
path: `{sprint_root}/closure/arch-drift-review.md`. Its findings table follows
`l3io-arch-review/references/review-report.md` (that skill's own reference), with each ID in the `#` column as `SD-{nn}-{n}`, where `{nn}` is
this sprint's two-digit number (the `sprint-{nn}` in `{sprint_root}`) — for example `SD-02-3`.

When `{spec_alignment}` is `true`, also pass the spec index and the ranges this sprint's
pointers name:

```bash
{spec_align} build --if-stale
{spec_align} sections --stories {sprint_root}/stories/*.md
```

The reviewer opens only those ranges, plus one section picked from
`{implementation_artifacts}/spec/spec-index.md` for a diff hunk no pointer covers, and ends
with a `Sections read:` footer listing every range it opened.

Record a disposition for every BLOCKER and MAJOR finding (a MINOR may have one too), then gate
on them against the reviewer's final `Blocker: N, Major: N, Minor: N` line:

```bash
{spec_align} disposition --review {sprint_root}/closure/arch-drift-review.md \
  --finding {finding_id} --disposition {disposition} [--spec {path#anchor}] [--adr {adr path}] \
  --spec-alignment {spec_alignment}
{spec_align} check-dispositions --review {sprint_root}/closure/arch-drift-review.md \
  --expect "{the reviewer's Blocker/Major/Minor line}"
```

BLOCKER/MAJOR are resolved before the sprint is marked done. Each one is either:
- fixed in code (`resolved-in-code`);
- justified by an accepted ADR (`adr-justified`); or
- when `{spec_alignment}` is `true`, carried to epic closure as a spec edit (`spec-updated`,
  architecture sections only) or as a proposal (`spec-proposal`).

A `check-dispositions` exit 2 blocks the sprint. MINOR: defer to the issues file (as
`--severity Low` — see §7).

## 7. Issue triage

Collect all Low severity issues found across phases 2–6. For each:

Bind `{phase_report}` from the phase that raised the finding:

| Phase | `{phase_report}` |
|---|---|
| `clean-release`, `adversarial` | `{sprint_root}/closure/adversarial-review.md` |
| `redteam` | `{sprint_root}/closure/redteam-report.md` |
| `ux-review` | `{sprint_root}/closure/ux-review.md` |
| `arch-drift` | `{sprint_root}/closure/arch-drift-review.md` |

```bash
uv run {pm_status} append-issue \
  --file {pm_issues_file} \
  --epic {epic_nnn} \
  --sprint {sprint_num} \
  --title "{issue_title}" \
  --source-phase {phase} --source-ref {finding_id} \
  --severity Low \
  --description "See {phase_report}"
```

`--key` is omitted — `append-issue` allocates `BL-{epic_key}-{nnn}` itself under a lock,
from the highest existing number for this epic; never construct the number here.

## 8. Blocked stories — closure exit vocabulary

Before writing the closure summary, check for stories currently in `status: blocked`.
These are distinct from failures: a blocked story has halted pending external
intervention (spec question, missing dependency, decision needed), not because of a
local defect. Iterating the fix loop against a blocked story does not help — the design
(`docs/superpowers/specs/2026-09-25-story-lifecycle-blocked-design.md` §6) halts the fix
loop per-story on blocked for exactly this reason.

Enumerate the sprint's blocked stories:

```bash
uv run {pm_status} show --state-root {pm_state_root} --epic {epic_key} --sprint {sprint_num}
```

The output renders each blocked story inline as `[blocked: <reason>]`. If any are
present, the closure report includes a `BLOCKED stories:` section listing key + reason,
and the closure exit line is **`BLOCKED:`** (not `FAILED:`) — matching the phase-status
vocabulary at `steps/execute/step-05-epic-loop.md:388`:

```
BLOCKED: sprint {sprint_num} of {epic_key} — {N} story/ies blocked pending external
resolution (see closure-report.md §Blocked stories)
```

**When both conditions apply — blocked stories AND unresolved Critical/High/Medium findings —
`BLOCKED:` wins over `FAILED:`.** The remedy differs: an unresolved finding is fixed by
another fix-loop iteration; a blocked story is fixed by resolving the external condition,
which no local iteration can produce. `BLOCKED:` is the more actionable exit because it names
what the operator has to do next.

If no stories are blocked, closure proceeds normally under the usual DONE/FAILED exit.

## 9. Closure summary

Write closure summary to `{sprint_root}/closure/closure-report.md`:
- Stories done, estimates vs actuals
- Blocked stories: key + reason (only when the count is > 0)
- Issues resolved: count by severity
- Issues deferred: count by severity
- Phases run vs skipped
