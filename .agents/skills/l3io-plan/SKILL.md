---
name: l3io-plan
description: Validate readiness, elaborate stories, estimate, build dependency graph, and produce an executable plan. Use when the user wants to plan across epics before execution, or to re-estimate existing ones. Use /l3io-plan for a full plan, /l3io-plan estimate [E{nnn}|E{nnn}-S{nn}] to re-estimate only.
---

# l3io-plan

Communicate all responses in `{communication_language}`.

## Conventions

- `{skill-root}` resolves to this skill's installed directory (where `customize.toml` lives).
- `{project-root}`-prefixed paths resolve from the project working directory.
- Bare paths (e.g. `steps/shared/step-00-activate.md`) resolve from `{skill-root}`.

## On Activation

Run: `uv run {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --key workflow`

If the script fails, resolve the `workflow` block by reading `{skill-root}/customize.toml`, then `{project-root}/_bmad/custom/l3io-plan.toml` (team), then `{project-root}/_bmad/custom/l3io-plan.user.toml` (personal) in order. Scalars override, arrays append.

`setup`, `configure`, and `install` are not recognized arguments here — `/l3io-setup` is the module's setup entry point. Config itself is resolved in step-00-activate per `{skill-root}/references/config-resolution.md`; an absent `modules.l3io-pm` section means the module has no overrides, not that it needs setup.

## Execution

**All modes — load first:**
```
{skill-root}/steps/shared/step-00-activate.md
```

Before reading any further state, apply the once-per-project setup pointer
(`{skill-root}/references/config-resolution.md` §5) — this skill is one of the two skills the
pointer is wired into. It fires only when `{l3io_pm_section_absent}` (bound in step-00-activate
§1, from config already resolved there) is `true` — a configured project gets no pointer at
all:

```bash
if [ "{l3io_pm_section_absent}" = "true" ]; then
  uv run {pm_status} notice --state-root {pm_state_root} --key setup-pointer && \
    echo "l3io-pm currently has no project-level configuration. /l3io-setup configures it if you want to."
fi
```

`notice` is keyed on `--key` alone, not a session — there is no cross-invocation session
identifier available (`{session_id}` is bound fresh per invocation), so this fires **at most
once ever** for this project, not once per invocation. Exit 1 means this key was already
recorded — print nothing further, permanently, for this key. Exit 2 means recording it
actually failed (never conflated with exit 1). Never halt on any branch, and never treat this
as a setup trigger.

```
{skill-root}/steps/shared/step-01-classify-work.md
```

**Full plan mode** (default — no args, or args that do not start with `estimate`):

Bind `{scope}` = `all` before loading step-estimate.

```
{skill-root}/steps/plan/step-backlog-intake.md         ← offers backlog → story promotion; never automatic
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
once written, and `l3io-execute` may be reading one concurrently. Their estimate blocks are a
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
   generated — run /l3io-plan (full) to produce a snapshot with the new numbers.
   Execution is unaffected: l3io-execute reads estimates from state, not the snapshot.
```

If no pointer exists, print nothing — there is no snapshot to go stale.
