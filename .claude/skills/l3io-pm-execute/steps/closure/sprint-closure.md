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
scope. They are the same reviewer (`bmad-review-adversarial-general`) over the same changed
files, and a reviewer's cost is dominated by reading the project — inviting it twice paid
that read twice for one pass's worth of context.

**Check each phase's gating separately; they differ.** Per the matrix in
`steps/shared/step-01-classify-work.md` §4, CONFIG work runs clean-release but skips
adversarial, so this is not an unconditional merge — collapsing them would silently extend
adversarial coverage to CONFIG:

| In `{skip_phases}` | Do this |
|---|---|
| neither | **one** invocation, both scopes (CODE and MIXED) |
| adversarial only | one invocation, `clean-release` scope alone (CONFIG) |
| both | run nothing (DOCS) |

**Scope every reviewer to the diff and named sections — never the repository.** Pass the
changed files (or the diff itself) plus the *specific* spec/standard sections that apply, by
path and section number. Never point a reviewer at the project and let it decide what to
read: a reviewer that loads the corpus pays a full `cache_write` over it before its first
thought, and then re-reads that prefix on every turn it takes. Scoped this way a reviewer's
spend measures at roughly **3.4% of a story's tokens**; unscoped it is a multiple of the work
under review. If a reviewer says it lacks context, name the additional section — do not widen
it to the repository.

Invoke `bmad-review-adversarial-general` with **the sprint's diff** and the scopes that
survived that check:

- scope `clean-release` — dead code, commented-out code, debug artifacts, TODO markers,
  and any secrets or credentials in changed files.
- scope `adversarial` — threat-model the sprint's changes.

Return findings **tagged by which scope raised them**, so triage stays per phase and the
closure report can still say which phases ran:

- `clean-release` CRITICAL/HIGH: fix immediately (re-invoke dev subagent). MEDIUM/LOW: defer to issues.
- `adversarial` CRITICAL/HIGH: block closure, fix loop (max `{max_fix_iterations}` iterations).
  MEDIUM: fix in place. LOW: defer.

## 4. Red team (skip if in skip_phases)

If `l3io-sec-redteam` is installed:
```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-sec[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```
**Redteam is not scoped like the reviewers above — give it a starting set, not a fence.**
The diff-scoping rule in §2–3 exists because a diff *is* a reviewer's whole input; redteam's
own method (`references/scope-mapping.md`, this skill) is different by design: it builds a
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

If `bmad-ux-review` is installed and sprint has UI-facing stories:
```bash
ls {project-root}/.claude/commands/bmad-ux-review.md 2>/dev/null \
  || ls ~/.claude/commands/bmad-ux-review.md 2>/dev/null \
  || echo "absent"
```
If present: invoke with story files that have UX acceptance criteria.
HIGH: fix. LOW/MEDIUM: defer.

## 6. Sprint architectural drift review (skip if in skip_phases)

If `l3io-arch-review` is installed: invoke Mode B (architectural review) on this sprint's
stories and **diff**, plus the ADRs and standard sections they bear on, by path — not the
repository (see §2–3).
BLOCKER/MAJOR: resolve before marking sprint done, or record an accepted ADR that justifies
leaving it. MINOR: defer to issues file (as `--severity Low` — see §7).

## 7. Issue triage

Collect all Low severity issues found across phases 2–6. For each:

```bash
python3 {pm_status} append-issue \
  --file {pm_issues_file} \
  --epic {epic_nnn} \
  --sprint {sprint_num} \
  --title "{issue_title}" \
  --source "{phase} ({finding_id})" \
  --severity Low
```

`--key` is omitted — `append-issue` allocates `BL-{epic_key}-{nnn}` itself under a lock,
from the highest existing number for this epic; never construct the number here.

Write closure summary to `{sprint_root}/closure/closure-report.md`:
- Stories done, estimates vs actuals
- Issues resolved: count by severity
- Issues deferred: count by severity
- Phases run vs skipped
