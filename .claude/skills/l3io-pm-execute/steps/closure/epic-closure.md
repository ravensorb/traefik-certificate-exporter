# Epic Closure Workflow

Communicate all responses in `{communication_language}`.

This file is loaded by step-06-epic-closure.md. Run each section in order.

## Dispatch rule for every spawn in this file

Every phase below that spawns or invokes a subagent — retrospective, adversarial review,
red team, UX, arch drift, and any fix-loop re-dispatch — brackets it with
`dispatch --event open` / `--event close`, same `--agent <name> --epic {epic_key}
--session-id {session_id}` identity on both, closed on **every** exit path.

Include `{agent_contract}` (verbatim — see `steps/shared/step-00-digest.md`) in every spawn prompt.
These are `bmad-*` and `l3io-*` agents that load no part of the activation digest; without it
they have no instruction to stop rather than wait.

Attribution is unchanged by the bracket: closure phases are **closure** spend, added on top of
the children's sum in the epic's own `actual` — never a child's `actual` and never
`orchestration` (`references/metrics-contract.md` §6). The bracket here buys stall detection,
not a change of bucket.

## 1. Retrospective

Spawn `bmad-retrospective` (or inline if not installed):
- Review all sprint retrospectives for this epic
- Summarize velocity, recurring pain points, and process improvements
- Identify top 3 learnings to carry forward

Produce:
- `retrospective_summary` (2–4 sentences)
- `retrospective_learnings` (bullet list, max 5 items)

Write retrospective report to `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/retrospective.md`.

## 2. Architectural drift review

Run only if `{work_type}` is CODE or MIXED AND `l3io-arch-review` is installed.

```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-arch[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```

If present: invoke l3io-arch-review Mode B (architectural review — review what was built vs
what was planned).
**Scope it, do not hand it the repository.** A reviewer pointed at the project pays a full
`cache_write` over the corpus before its first thought, then re-reads that prefix every turn.
Pass:
- ADR paths: `{implementation_artifacts}/epic-{epic_nnn}/arch/*.md`
- Story file paths: `{implementation_artifacts}/epic-{epic_nnn}/*/stories/*.md`
- The epic's cumulative **diff**, not the working tree
- Named standard sections the ADRs invoke, by path and section number

Findings:
- BLOCKER/MAJOR: must be resolved before closure completes (fix loop, max
  `{max_fix_iterations}` iterations) or recorded as an accepted ADR that justifies leaving it.
- MINOR: append to issues file via `pm-status.py append-issue` (as `--severity Low`).

## 3. Epic security review

Run only if `{work_type}` is CODE or MIXED AND `l3io-sec-redteam` is installed.

```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-sec[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```

If present: spawn `l3io-sec-redteam` per its documented orchestrator-invocation contract
(`SKILL.md` "On Activation" step 1 — explicit scope, artifact paths, and output path).
Sprint closure already runs redteam per sprint (`sprint-closure.md` §4), but a sprint's
surface map is the narrowest one it ever builds; an epic-wide analysis is where entry
points, trust boundaries, and auth checkpoints spanning multiple sprints' changes actually
come into view. Give it a starting set, not a fence — the same distinction sprint closure
draws, for the same reason (redteam's own method, `references/scope-mapping.md`, builds its
surface map from what's actually implemented, and "a scope with no entry points or no trust
boundaries is incomplete — expand until the picture is coherent"). Pass:

- **Scope statement**: epic-level security analysis, epic `{epic_key}` — identify this
  explicitly as epic-level, not sprint-level, so the agent maps the wider surface rather than
  replaying its sprint-scoped passes.
- **Seed artifacts** (a starting set, not a fence): the epic's cumulative **diff**, the story
  file paths (`{implementation_artifacts}/epic-{epic_nnn}/*/stories/*.md`), and the ADR paths
  (`{implementation_artifacts}/epic-{epic_nnn}/arch/*.md`).
- **Explicit permission to widen**: it may read beyond the seeds to trace entry points, trust
  boundaries, data flows, and auth checkpoints spanning the epic's sprints — that is its
  method, not a workaround.
- **Output path**: `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/redteam-report.md`.

Cost discipline takes the form of accountability, not a fence: start from the seed artifacts,
widen only with a reason, and report what it widened to and why.

**Findings use redteam's own severity vocabulary** (`references/findings-report.md`), not the
arch reviewer's BLOCKER/MAJOR/MINOR:
- CRITICAL/HIGH: must be resolved before closure completes (fix loop, max
  `{max_fix_iterations}` iterations) or recorded as an accepted ADR that justifies leaving it.
- MEDIUM: fix in place, or record an accepted ADR that justifies leaving it.
- LOW: append to issues file via `pm-status.py append-issue` (`--severity Low`).
- OBSERVATION: note in the closure report; no action required.

## 4. Issue triage

Collect all Low severity issues identified during the epic's sprint closures (already in issues file).
Review for any that should be promoted to Medium/High given the full epic context.

For any promoted items: update severity in the issues file (re-write the item via `append-issue`
after removing the old entry manually, or note for the implementer to do so in-place).

Output triage summary: count of issues by severity, count promoted.

## 5. Closure report

Write `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/closure-report.md` containing:
- Epic goal and final status
- Estimate vs actual table (all five metrics)
- Sprint velocity summary
- Retrospective learnings
- Outstanding issues count (by severity)
- ADRs produced (if any)

## 6. Progress render and report regeneration

Epic closure runs once per epic, after all of its sprints have finished, so it is not competing
with sibling sprints for stdout — render unconditionally:

```bash
python3 {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format tree

python3 {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format md --out {implementation_artifacts}/progress-report.md
```

Print the tree verbatim. Both commands are read-only with respect to state; a failure in either
is a reporting problem — note it in one line and continue rather than failing epic closure.
