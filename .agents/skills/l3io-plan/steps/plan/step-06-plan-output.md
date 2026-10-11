# Step 06: Plan Output

Communicate all responses in `{communication_language}`.

Writes the plan snapshot and updates the stable pointer. This is the final step of full plan mode.

---

## 1. Determine plan filename

Today's date: read from the system (`date +%Y-%m-%d`).

List existing plan snapshots in `{planning_artifacts}/`:
```bash
ls {planning_artifacts}/plan-{today}-v*.yaml 2>/dev/null | sort -V | tail -1
```

If none exist for today → filename = `plan-{today}-v1.yaml`.
If the highest existing version is `vN` → filename = `plan-{today}-v{N+1}.yaml`.

Set `{plan_filename}` = `plan-{today}-v{version_number}.yaml`.

## 2. Build the plan snapshot

Construct `{plan_snapshot}` with this structure (write verbatim to file — preserve all fields):

```yaml
generated: "{timestamp}"               # ISO-8601 UTC
plan_version: {version_number}         # integer; auto-increments per-day, resets on new date
readiness: {readiness}                 # green | amber | red
stories_elaborated: {elaborated_count} # from step-03; 0 if step was skipped
total_epics_in_scope: {in_scope_count} # active + backlog (not archived)

phases:
{phases_yaml_block}                    # exactly the phases list from step-05

readiness_detail:
{readiness_detail_yaml_block}          # per-epic: key, status (green/amber/red), gaps list

arch_gate_summary:
  ran: false                           # always false at plan time — arch gate runs in l3io-execute
  reviewers: []
  findings: []
```

Where `{phases_yaml_block}` includes the estimate sub-block for each phase if estimates are present:

```yaml
phases:
  - phase: 1
    parallel: true
    epics: ["E001", "E002"]
    dependencies: []
    estimate:
      estimates_as_of: "{timestamp}"     # point-in-time; see below
      wall_clock_hours_low: {max(epic.elapsed_hours_low) if parallel else Σ elapsed_hours_low}
      wall_clock_hours_high: {max(epic.elapsed_hours_high) if parallel else Σ elapsed_hours_high}
      man_hours_low: {Σ man_hours_low}
      man_hours_high: {Σ man_hours_high}
      hitl_hours_low: {Σ hitl_hours_low}
      hitl_hours_high: {Σ hitl_hours_high}
      tokens_k_min: {Σ tokens_k_min}
      tokens_k_max: {Σ tokens_k_max}
      cost_low: {Σ cost_low}             # each epic's cost_low/high is itself derived from its
      cost_high: {Σ cost_high}           # tokens_k range x rates — never re-derived here, only summed
      confidence: {weakest confidence across epics}
```

For parallel phases, wall_clock (`elapsed_hours`) = max(epic.elapsed_hours) not sum — parallel phases run concurrently. For sequential phases, wall_clock = sum. Man-hours, hitl-hours, tokens, and cost always sum regardless of parallelism.

**These blocks are a report, not an input.** The authority for estimates is the state node
files under `{pm_state_root}`, written by `pm-status.py estimate-story` / `estimate-rollup`.
Nothing reads these numbers back: `l3io-execute` extracts only the phases list, `generated`,
and `confidence` from the snapshot, and the critical path in step-05 is computed from epic
estimates in state. They exist so a human reading the snapshot sees what the plan cost was
projected at.

`estimates_as_of` therefore records when the numbers were true, and the snapshot is never
rewritten to refresh them — `/l3io-plan estimate` updates state and leaves this file alone.
A snapshot is immutable once written (`l3io-execute` step-03 treats snapshots as inert
history), so a stamp that goes stale is correct behavior; a snapshot that mutates under an
executing run is not. To get current numbers into a snapshot, generate a new one.

## 3. Write plan snapshot

The version scan in section 1 is read-then-write with no lock. Two plan runs on the same day —
routine when several agents share one checkout — both read `v1` and both compute `v2`, and the
second write would silently destroy the first. Re-check immediately before writing, and never
overwrite an existing snapshot:

```bash
test -e {planning_artifacts}/{plan_filename} && echo TAKEN || echo FREE
```

If `TAKEN`, another run claimed this version between section 1 and now. Re-run section 1 to pick
the next free version, rebind `{plan_filename}`, and re-check. Repeat until `FREE` (at most 3
attempts; if still taken, BLOCKED: concurrent plan runs are contending for a version number).

Write `{plan_snapshot}` as YAML to `{planning_artifacts}/{plan_filename}`.

## 4. Update plan-output-meta.yaml

Order matters and is not interchangeable: the snapshot must be written and confirmed before the
pointer is updated. `l3io-execute` treats this file as the sole authority for which plan is
current, so a pointer naming a snapshot that does not exist blocks execution outright. If
section 3 did not complete, do not write this file — leaving the previous pointer intact is
strictly better than publishing a dangling one.

This file is a **pointer plus summary scalars — never a second copy of the plan.** It used to
repeat the whole `phases:` list, giving the plan two sources of truth that could diverge under
hand-editing while no consumer benefited: `l3io-execute` reads phases only from the snapshot,
and `l3io-help` wants nothing but the count. Write `phase_count` and leave the list to the
snapshot.

Write `{planning_artifacts}/plan-output-meta.yaml` (overwrite):

```yaml
current_plan: "{plan_filename}"
generated: "{timestamp}"
readiness: {readiness}
stories_elaborated: {elaborated_count}
total_epics_in_scope: {in_scope_count}
phase_count: {phase_count}             # length of the snapshot's phases list
```

Do not add fields here to save a consumer from opening the snapshot. Anything per-phase or
per-epic belongs in `{plan_filename}` only.

## 5. Output plan summary

### 5.0 Compute the critical path, here and not earlier

`step-05` deliberately computes only the **structural** longest chain, because the estimates a
weighted path needs are written by `step-estimate`, which runs after it. This step builds the
per-phase estimate blocks in §2 from epic estimates read *after* that, so this is the first
point in the run where the numbers are both present and current. Compute it from the §2 blocks
you already have — do not re-read state, and do not inherit a binding from `step-05`.

Phases run in order and epics inside a `parallel: true` phase run concurrently, so:

- `{total_time_low}` = Σ over phases of that phase's `elapsed_hours_low`
- `{total_time_high}` = Σ over phases of that phase's `elapsed_hours_high`

  These are the §2 phase values, which already apply the right rule per phase — `max` of the
  phase's epics when parallel, `sum` when sequential. Summing them across phases is correct
  because phases themselves are always sequential.

- `{critical_path_str}` = the **pacesetter chain**: in each phase, the epic with the largest
  `estimate.elapsed_hours_high`, joined in phase order with ` → `. That epic is the one whose
  duration the phase cannot finish before, so it is what a phase's wall-clock is actually made
  of. A sequential phase contributes its single epic.

If no epic carries an estimate — possible only if `step-estimate` was skipped — bind
`{critical_path_str}` to the structural `{longest_chain_epics}` from step-05 and omit the hours
in parentheses. Say "structural" on the line so nobody reads an unweighted chain as a costed
one.

**Why this moved.** Reading the path from `step-05` meant a first plan always printed "all
epics in phase order, no differentiation" — step-05's own fallback, taken because state held no
estimates yet — and a re-plan printed the previous generation's, overwritten two steps later.
`{critical_path_str}`, `{total_time_low}` and `{total_time_high}` were never bound anywhere
either: each appeared exactly once, at its use site below.

### 5.1 Check sprint load — the one signal that needs the estimates

**The structural check already ran, at `step-05-dependency-graph.md` §6.** Every finding a
reorg can act on needs only `depends_on`, so it is reported three steps earlier, before a user
pays to estimate a shape they may be about to change. Do not repeat it here.

What could not run there is sprint load, because it needs the `elapsed_hours` that
`step-estimate` has only just written:

```bash
uv run {pm_status} dump-plan --state-root {pm_state_root} \
  | uv run {skill-root}/scripts/plan-graph.py analyze
```

Bind `{balance_advisory}` from the `sprint-imbalance` findings alone:

- One or more present →
  `⚖ Sprint load is uneven: {epic} sprints range {low}–{high} hrs (ratio {ratio}). /l3io-plan reorg can rebalance them within the dependency graph.`
- None → bind the empty string and print nothing.

**`sprint-imbalance` is `info`, not `warn`, and this advisory is the reason it still exists.**
A reorg cannot make work smaller, so load is never a reason to re-place work on its own — it is
an impact, reported (ADR-0011). But an epic whose sprints differ several-fold is still worth
saying out loud, because rebalancing *within* the structure is a legal move and the user has no
other way to learn that it is available.

**Ignore every other finding here.** The `warn` ones were reported at step-05 and acting on
them twice in one run would train a reader to skip both.

If the analyzer fails or is absent, bind the empty string and carry on — a missing advisory must
never fail a plan run that otherwise succeeded.

### 5.2 Print it

Always print the human-readable summary:

```
📋 Plan complete — {plan_filename}

Scope: {in_scope_count} epics across {phase_count} phases

Phase 1 (parallel): {epic_keys} — est. {time_low}–{time_high} hrs wall-clock, {cost_low}–{cost_high} cost
Phase 2 (sequential): {epic_keys} — est. {time_low}–{time_high} hrs wall-clock, {cost_low}–{cost_high} cost

Critical path: {critical_path_str} ({total_time_low}–{total_time_high} hrs)

Readiness: {readiness}
{balance_advisory}
Plan written to: {planning_artifacts}/{plan_filename}
Stable pointer: {planning_artifacts}/plan-output-meta.yaml

Next: run /l3io-execute to start execution.
```

When `{balance_advisory}` is empty, omit the line entirely rather than printing a blank one.

If `{plan_output}` is `console`, skip writing files in steps 3 and 4 — print only.

## 6. Output status line

```
Step 06 complete — plan: {plan_filename}, phases: {phase_count}, readiness: {readiness}
DONE — Plan: {plan_filename}, epics: {in_scope_count}, phases: {phase_count}
```
