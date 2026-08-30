---
name: l3io-pm-plan
description: Validate readiness, elaborate stories, estimate, build dependency graph, and produce an executable plan. Use /l3io-pm-plan for a full plan, /l3io-pm-plan estimate [E{nnn}|E{nnn}-S{nn}] to re-estimate only.
---

# l3io-pm-plan

Communicate all responses in `{communication_language}`.

## Conventions

- `{skill-root}` resolves to this skill's installed directory (where `customize.toml` lives).
- `{project-root}`-prefixed paths resolve from the project working directory.
- Bare paths (e.g. `steps/shared/step-00-activate.md`) resolve from `{skill-root}`.

## On Activation

Run: `python3 {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --key workflow`

If the script fails, resolve the `workflow` block by reading `{skill-root}/customize.toml`, then `{project-root}/_bmad/custom/l3io-pm-plan.toml` (team), then `{project-root}/_bmad/custom/l3io-pm-plan.user.toml` (personal) in order. Scalars override, arrays append.

Load `{skill-root}/assets/module-setup.md` first **only** when the user passes `setup`, `configure`, or `install`. Config itself is resolved in step-00-activate per `{skill-root}/references/config-resolution.md`; an absent `modules.l3io-pm` section means the module has no overrides, not that it needs setup.

## Execution

**All modes — load first:**
```
{skill-root}/steps/shared/step-00-activate.md
{skill-root}/steps/shared/step-01-classify-work.md
```

**Full plan mode** (default — no args, or args that do not start with `estimate`):

Bind `{scope}` = `all` before loading step-estimate.

```
{skill-root}/steps/plan/step-02-readiness-check.md
{skill-root}/steps/plan/step-03-story-elaboration.md   ← skipped if work_type is DOCS or CONFIG
{skill-root}/steps/plan/step-04-load-state.md
{skill-root}/steps/plan/step-05-dependency-graph.md
{skill-root}/steps/shared/step-estimate.md
{skill-root}/steps/plan/step-06-plan-output.md
```

**Estimate mode** (args start with `estimate`):

Parse scope from arg: `estimate` → `{scope}=all`; `estimate E{nnn}` → `{scope}=E{nnn}`; `estimate E{nnn}-S{nn}` → `{scope}=E{nnn}-S{nn}`. Then load:
```
{skill-root}/steps/shared/step-estimate.md
```
Output estimate summary only. No graph, no elaboration, no plan document.

Estimate mode writes state and **must not touch any plan snapshot** — snapshots are immutable
once written, and `l3io-pm-execute` may be reading one concurrently. Their estimate blocks are a
point-in-time report stamped `estimates_as_of` (see `step-06-plan-output.md` §2); re-estimating
makes that stamp stale, which is the stamp doing its job.

Say so rather than silently leaving a stale report behind. After the summary:

```bash
test -f {planning_artifacts}/plan-output-meta.yaml && \
  grep '^current_plan:' {planning_artifacts}/plan-output-meta.yaml
```

If a pointer exists, print:
```
ℹ️  Estimates updated in state. {current_plan} still shows the estimates from when it was
   generated — run /l3io-pm-plan (full) to produce a snapshot with the new numbers.
   Execution is unaffected: l3io-pm-execute reads estimates from state, not the snapshot.
```

If no pointer exists, print nothing — there is no snapshot to go stale.
