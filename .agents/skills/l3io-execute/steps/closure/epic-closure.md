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

Run unless `{work_type}` is DOCS, AND only if `l3io-arch-review` is installed.

```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-arch[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```

If present: invoke l3io-arch-review Mode B (architectural review — review what was built vs
what was planned).
**Scope it, do not hand it the repository.** A reviewer pointed at the project pays a full
`cache_write` over the corpus before its first thought, then re-reads that prefix every turn.
Pass:
- ADR paths: the output of `{spec_align} adrs --epic {epic_key}` — the epic's ADRs in
  `docs/adr/`, plus any still in the old per-epic home
- When `{spec_alignment}` is `true`: `{implementation_artifacts}/spec/spec-index.md` and the
  ranges from `{spec_align} build --if-stale` followed by
  `{spec_align} sections --stories {implementation_artifacts}/epic-{epic_nnn}/*/stories/*.md`.
  Open only those ranges, plus one index-picked section for a diff hunk no pointer covers,
  and end the review with a `Sections read:` footer listing every range opened.
- Story file paths: `{implementation_artifacts}/epic-{epic_nnn}/*/stories/*.md`
- The epic's cumulative **diff**, not the working tree
- Named standard sections the ADRs invoke, by path and section number
- **Output path**: `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/arch-drift-review.md` — one finding per entry, each with an ID (`AD-{n}`)

Findings — record a disposition for every BLOCKER and MAJOR (a MINOR may have one), then gate
on them, exactly as sprint closure §6 does:

```bash
{spec_align} disposition --review {implementation_artifacts}/epic-{epic_nnn}/epic-closure/arch-drift-review.md \
  --finding {finding_id} --disposition {disposition} [--spec {path#anchor}] [--adr {adr path}] \
  --spec-alignment {spec_alignment}
{spec_align} check-dispositions --review {implementation_artifacts}/epic-{epic_nnn}/epic-closure/arch-drift-review.md \
  --expect "{the reviewer's Blocker/Major/Minor line}"
```

- BLOCKER/MAJOR: must be resolved before closure completes. Each one is either:
  - fixed in code under the fix loop (max `{max_fix_iterations}` iterations,
    `resolved-in-code`);
  - recorded as an accepted ADR that justifies leaving it (`adr-justified`); or
  - when `{spec_alignment}` is `true`, written back to the architecture spec
    (`spec-updated`) or proposed for the PRD/UX/epic docs (`spec-proposal`), both carried out
    by §2a.

  A `check-dispositions` exit 2 blocks closure.
- MINOR: append each to the issues file:
  ```bash
  uv run {pm_status} append-issue --file {pm_issues_file} \
    --epic {epic_nnn} --sprint "" \
    --title "{finding_text}" \
    --source-phase epic-arch-review --source-ref {finding_id} \
    --severity Low \
    --description "See {implementation_artifacts}/epic-{epic_nnn}/epic-closure/arch-drift-review.md"
  ```

## 2a. Spec sync (only when `{spec_alignment}` is `true`)

Runs after §2's fix loop. The plan costs no tokens, and it decides whether an agent runs at
all:

```bash
{spec_align} sync-plan --epic {epic_key}
```

It prints JSON `{"epic": …, "items": […]}`. **If `items` is empty, go to §3 — nothing is
dispatched.**

Otherwise take the lease. Parallel epic closures share one working tree:

```bash
{spec_align} lease acquire --owner {epic_key} --wait-minutes 15
```

**Exit 5** (still held after 15 minutes): dispatch nothing. Turn every pending item into a
pointer-only proposal and backlog item, then go to §3:

```bash
{spec_align} sync-plan --epic {epic_key} --defer
```

**Exit 0:** dispatch one agent as `--agent l3io-spec-sync --epic {epic_key}`, bracketed per
this file's dispatch rule. Give it the `items` JSON,
`{implementation_artifacts}/spec/spec-index.md` and `{agent_contract}`, with these
instructions:

- **Each `spec-updated` item.** Edit only the section its `range` names, so that the spec
  describes what was built. When the item has an ADR, add a relative link to it. Then run
  `{spec_align} commit --epic {epic_key} --finding {id} --paths {the spec file}`.
  - Exit 2 names the problem: an edit outside the section, or a renamed anchor that stories
    point to. Pass `--rename-anchor OLD=NEW` when the rename is intended.
  - Fix and retry once. On a second refusal, restore the file
    (`git -C {project-root} restore -- {the spec file}`) and handle the item as a proposal
    (below).
- **Each `adr-link` item.** Add a relative link to the ADR inside the section, then run
  `{spec_align} commit --epic {epic_key} --adr {adr} --paths {the spec file}`.
- **Each `spec-proposal` item**, and any item refused twice above. Write
  `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/spec-proposals/{id}.md`, giving the
  target pointer, the proposed change, why, and the finding. Then run
  `{spec_align} propose --epic {epic_key} --finding {id}` (use `--adr {adr}` for an ADR link).
- Open nothing but the index, the listed ranges, and the review rows the items carry.

`commit` and `propose` record each backlog item themselves (`spec-change`, `spec-proposal`) —
do not call `append-issue` for them.

Release the lease on **every** exit path:

```bash
{spec_align} lease release --owner {epic_key}
```

Then run `{spec_align} check-pointers --all`, and carry any broken pointer it prints into the
closure report. It does not block.

## 3. Epic security review

Run unless `{work_type}` is DOCS, AND only if `l3io-sec-redteam` is installed.

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
draws, for the same reason (redteam's own method, `l3io-sec-redteam/references/scope-mapping.md`, builds its
surface map from what's actually implemented, and "a scope with no entry points or no trust
boundaries is incomplete — expand until the picture is coherent"). Pass:

- **Scope statement**: epic-level security analysis, epic `{epic_key}` — identify this
  explicitly as epic-level, not sprint-level, so the agent maps the wider surface rather than
  replaying its sprint-scoped passes.
- **Seed artifacts** (a starting set, not a fence): the epic's cumulative **diff**, the story
  file paths (`{implementation_artifacts}/epic-{epic_nnn}/*/stories/*.md`), and the ADR paths
  (`{spec_align} adrs --epic {epic_key}`).
- **Explicit permission to widen**: it may read beyond the seeds to trace entry points, trust
  boundaries, data flows, and auth checkpoints spanning the epic's sprints — that is its
  method, not a workaround.
- **Output path**: `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/redteam-report.md`.

Cost discipline takes the form of accountability, not a fence: start from the seed artifacts,
widen only with a reason, and report what it widened to and why.

**Findings use redteam's own severity vocabulary** (`l3io-sec-redteam/references/findings-report.md`), not the
arch reviewer's BLOCKER/MAJOR/MINOR:
- CRITICAL/HIGH: must be resolved before closure completes (fix loop, max
  `{max_fix_iterations}` iterations) or recorded as an accepted ADR that justifies leaving it.
- MEDIUM: fix in place, or record an accepted ADR that justifies leaving it.
- LOW: append each to the issues file:
  ```bash
  uv run {pm_status} append-issue --file {pm_issues_file} \
    --epic {epic_nnn} --sprint "" \
    --title "{finding_text}" \
    --source-phase epic-redteam --source-ref {finding_id} \
    --severity Low \
    --description "See {implementation_artifacts}/epic-{epic_nnn}/epic-closure/redteam-report.md"
  ```
- OBSERVATION: note in the closure report; no action required.

## 4. Issue triage

Collect all Low severity issues identified during the epic's sprint closures (already in issues file).
Review for any that should be promoted to Medium/High given the full epic context.

For any promoted item, change its severity in place — never remove and re-append it:

```bash
uv run {pm_status} update-issue --state-root {pm_state_root} --key {BL key} \
  --severity {Medium|High|Critical} --note "{why, given the full epic}" --cause cli
```

Count an item as promoted only when the command prints `OK update-issue … severity Low -> …`.

Output triage summary: count of issues by severity, count promoted.

## 4a. Blocked stories — epic exit vocabulary

Before writing the closure report, check every sprint for stories in
`status: blocked`. Blocked stories block epic closure the same way an unresolved
Critical/High/Medium finding does, and are surfaced with distinct vocabulary
(`docs/superpowers/specs/2026-09-25-story-lifecycle-blocked-design.md` §7):

```bash
uv run {pm_status} show --state-root {pm_state_root} --epic {epic_key}
```

The `blocked_stories: N` line appears when the epic has any currently-blocked
stories, with a `cumulative block events` count that surveys the whole life of
the epic. If N > 0:

- The closure report grows a `Blocked stories:` section listing key + sprint +
  reason for every currently-blocked story.
- The epic exit line is **`BLOCKED:`** (not `FAILED:`), matching
  `steps/execute/step-05-epic-loop.md`'s phase-status vocabulary:

  ```
  BLOCKED: {epic_key} — {N} story/ies blocked pending external resolution (see
  closure-report.md §Blocked stories)
  ```

**When both conditions apply — blocked stories AND unresolved
Critical/High/Medium findings — `BLOCKED:` wins over `FAILED:`.** The remedies
differ: unresolved findings are fixed by another fix-loop iteration; blocked
stories are fixed by resolving the external condition, which no local iteration
can produce. `BLOCKED:` is the more actionable exit because it names what the
operator has to do next.

Epic closure does not attempt to resolve blocks — the resolution happens outside
the loop when the external condition changes. When that happens, the operator
transitions each blocked story to `in-progress`, and the epic can complete on a
subsequent run.

## 5. Closure report

Write `{implementation_artifacts}/epic-{epic_nnn}/epic-closure/closure-report.md` containing:
- Epic goal and final status
- Estimate vs actual table (all five metrics)
- Sprint velocity summary
- Retrospective learnings
- Blocked stories: key + sprint + reason (only when the count is > 0 — §4a)
- Outstanding issues count (by severity)
- ADRs produced (if any)
- **Spec changes** (when `{spec_alignment}` is `true`):
  - one row per disposition in the epic's `drift-dispositions.yaml` files: finding,
    disposition, commit SHA or proposal file, and backlog key;
  - the spec index's `bytes` and `sections` (its header line 2);
  - the number of ranges across every review's `Sections read:` footer;
  - spec sync's share of the epic's fresh tokens (input + output + cache_write): run
    `usage --agent l3io-spec-sync --epic {epic_key}` with the same transcript arguments as
    this epic's actuals capture, and divide by the epic's `actual.tokens_k` fresh total.

  When the share is above 5%, add the line `⚠ spec sync used {share}% of fresh tokens
  (budget 5%)`. It blocks nothing.

## 6. Progress render and report regeneration

Epic closure runs once per epic, after all of its sprints have finished, so it is not competing
with sibling sprints for stdout — render unconditionally:

```bash
uv run {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format tree

uv run {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format md --out {implementation_artifacts}/progress-report.md
```

Print the tree verbatim. Both commands are read-only with respect to state; a failure in either
is a reporting problem — note it in one line and continue rather than failing epic closure.

## 7. Commit checkpoint

Epic closure writes actuals, calibration samples, dispositions, proposals and the spec index.
Commit them as sprint closure does (`steps/sprint/step-04-sprint-closure.md` §9). The
`docs(spec)` commits that §2a made are already in history.

```bash
git -C {project-root} rm -r --cached --quiet --ignore-unmatch -- '{implementation_artifacts}/state/*.lock'
git add {implementation_artifacts}/state/ \
        {implementation_artifacts}/epic-{epic_nnn}/ \
        {planning_artifacts}/
# The spec index exists only once spec alignment has run; `git add` aborts the
# whole command on a pathspec that matches nothing, so stage it separately.
[ -d {implementation_artifacts}/spec ] && git add {implementation_artifacts}/spec/
git status --short
git commit -s -m "chore({epic_key}): close epic"
```

If unrelated files appear in `git status`, stage only these paths. If nothing is staged, skip
the commit.
