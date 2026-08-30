---
name: l3io-pm-help
description: Read project state and recommend the exact next l3io-pm action. Use /l3io-pm-help progress for a plan-aware progress tree — which phase, epic, sprint, and stories are in flight.
---

# l3io-pm-help

Communicate all responses in `{communication_language}`.

## On Activation

Run: `python3 {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --key workflow`

If the script fails, read `{skill-root}/customize.toml` directly.

Load `{skill-root}/assets/module-setup.md` first **only** when the user passes `setup`,
`configure`, or `install`. An absent `modules.l3io-pm` section means the module has no
overrides, not that it needs setup.

**Recognized argument — `progress`:** run section 1 (config) and section 2 (layout
detection) exactly as written, then jump to [Progress Mode](#progress-mode) and skip
sections 3-5. The layout gate still applies: a legacy tree short-circuits to the migration
recommendation, because the progress report reads only the sharded layout.

## Execution

### 1. Load paths from config

Resolve config through BMad core's resolver — full contract in
`{skill-root}/references/config-resolution.md`:

```bash
uv run --python 3.11 {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}
```

If the resolver is missing or fails, BMad core is not installed here — stop and tell the
user to run the BMad installer. Extract, applying the default when a key is absent:

- `{output_folder}` — `core.output_folder` (default `{project-root}/_bmad-output`)
- `{implementation_artifacts}` — `modules.l3io-pm.implementation_artifacts`
  (default `{output_folder}/implementation-artifacts`)
- `{planning_artifacts}` — `modules.l3io-pm.planning_artifacts`
  (default `{output_folder}/planning-artifacts`)
- Set `{pm_state_root}` = `{implementation_artifacts}/state`
- Set `{pm_issues_file}` = `{pm_state_root}/issues.yaml`
- Set `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py` (self-installed by the
  other PM skills; l3io-pm-help only reads, it does not self-install)

Then check whether `{pm_status}` is actually on disk and bind `{pm_status_present}`:

```bash
[ -f {project-root}/_bmad/scripts/pm-status.py ] && echo present || echo absent
```

**Staleness check** — when present, compare its version against this skill's own
`module_version` (`{skill-root}/module.yaml`, which moves with every release). Deriving the
comparison target from `module.yaml` means there is no hardcoded minimum version to drift out
of date as this skill is released forward:

```bash
INSTALLED=$(python3 {project-root}/_bmad/scripts/pm-status.py --version 2>/dev/null | awk '{print $2}')
EXPECTED=$(grep -m1 '^module_version:' {skill-root}/module.yaml | awk '{print $2}')
echo "installed=${INSTALLED:-none} expected=$EXPECTED"
```

Bind `{pm_status_stale}` = `yes` when `$INSTALLED` is empty (older copies predate
`--version`, or the read failed — never treat an unreadable version as current) or sorts
older than `$EXPECTED`:
`[ -z "$INSTALLED" ] || [ "$(printf '%s\n%s\n' "$EXPECTED" "$INSTALLED" | sort -V | head -1)" != "$EXPECTED" ]`.
Otherwise `no`.

**Never invoke `{pm_status}` when it is absent.** On a fresh install nothing has
self-installed it yet, so every `{pm_status}` call below is conditional: when
`{pm_status_present}` is `absent`, read each `epic.yaml` directly instead (it is plain YAML).
**A stale copy is different — usable but suspect:** `{pm_status}` calls below stay
conditional on presence only, not staleness, so keep using it as normal; the difference is
that section 5's recommendation calls this out prominently, because a subcommand the
installed copy lacks fails as an opaque argparse error rather than a clear one.

Note in the report, whichever applies:

```
pm-status.py not installed yet — reading epic.yaml files directly. Run /l3io-util-doctor to
install it (l3io-pm-help only reads; it does not self-install).
```

```
⚠️  pm-status.py at {project-root}/_bmad/scripts/pm-status.py is stale (installed
{installed}, this skill ships {expected}). Run /l3io-util-doctor to refresh it — some
subcommands newer skills rely on may be missing until then.
```

Neither is a hard blocker: everything l3io-pm-help needs can still be read.

### 2. Detect state layout — before reading anything, and before any recommendation

**This section gates every rule in section 4.** l3io-pm-help is the command an upgrading user
is most likely to run first, and its state probes only understand the sharded layout: against
a legacy tree every probe returns "(none)", which looks identical to an empty new project.
Recommending "create your project backlog" there would author a fresh backlog on top of live
work. So the layout is established first, and a legacy layout short-circuits to the migration
recommendation.

Use the identical three-way count `step-00-activate.md` performs — count all three, do not
stop at the first match:

```bash
SHARDED=$([ -d "{implementation_artifacts}/state" ] && echo 1 || echo 0)
LEGACY_EPIC=$([ -d "{project-root}/_bmad/state" ] && echo 1 || echo 0)
LEGACY_FLAT=$([ -f "{implementation_artifacts}/sprint-status.yaml" ] && echo 1 || echo 0)
echo "sharded=$SHARDED legacy-per-epic=$LEGACY_EPIC legacy-flat=$LEGACY_FLAT"
```

**If more than one is 1** → stop here. Print this and nothing else — do not read state, do
not build a snapshot, do not recommend anything:

```
BLOCKED: multiple state layouts detected (sharded=$SHARDED legacy-per-epic=$LEGACY_EPIC
legacy-flat=$LEGACY_FLAT). An earlier migration did not finish. Do not run any l3io-pm skill
until this is resolved — inspect both locations and remove the stale one, then re-run
/l3io-util-doctor migrate-state.
```

**If only the legacy per-epic layout or only the legacy flat layout** → stop here. Report
what was found and give exactly one recommendation:

```
⚠️  Legacy state layout detected (legacy per-epic layout = _bmad/state/, legacy flat layout
= flat sprint-status.yaml). Your project has existing l3io-pm state in a layout the current
skills no longer read.

Next action:  /l3io-util-doctor migrate-state

Nothing else should run first. The migration is non-destructive until its final stage and
keeps your originals as .legacy backups.
```

Never recommend `bmad-create-epics-and-stories`, `/l3io-pm-plan`, or `/l3io-pm-execute` on
this branch — a legacy tree means work already exists, and every one of those would either
block or write over it.

**If only sharded** → continue to section 3.

**If all three are 0** → possible first run. Before treating it as a blank project, rule out
an orphan caused by `implementation_artifacts` having been repointed — this is the same check
`step-00-activate.md` runs, and for the same reason: an empty probe result is not proof there
is no history.

```bash
git -C {project-root} ls-files -- '*/state/active/epic-*/epic.yaml' 'state/active/epic-*/epic.yaml' 2>/dev/null | head -5
find {project-root} -maxdepth 5 -type d -name active -path '*/state/*' 2>/dev/null | head -5
```

(The second pathspec, with no leading `*/`, catches the case where `implementation_artifacts`
equals `project-root` — git's fnmatch-pathname semantics need one literal segment before
`state/`.)

If either prints a path that is not under `{implementation_artifacts}/state`, stop here:

```
BLOCKED: state found at <printed-path> but implementation_artifacts resolves to
{implementation_artifacts}. Did implementation_artifacts change? Refusing to recommend
starting a blank project over existing state.
```

If both print nothing → genuine first run. Continue to section 3; rule 1 in section 4 may
now fire safely.

### 3. Read state files

```bash
ls -d {pm_state_root}/active/epic-*/ 2>/dev/null || echo "(none)"
ls -d {pm_state_root}/planned/epic-*/ 2>/dev/null || echo "(none)"
cat {pm_issues_file} 2>/dev/null || echo "(absent)"
cat {planning_artifacts}/plan-output-meta.yaml 2>/dev/null || echo "(absent)"
```

For each active/planned epic directory found, read its `epic.yaml` directly (key, title,
status, `_lock`, `depends_on`). If `{pm_status_present}` is `present`, you may instead use
`python3 {pm_status} show --state-root {pm_state_root} --epic {key}` for a computed roll-up
including sprint/story counts. If it is `absent`, use the direct read only.

Also surface one read-only health fact — state that is gitignored will never be committed,
which defeats the point of the layout:

```bash
git -C {project-root} check-ignore -q {pm_state_root} && echo IGNORED || echo TRACKED
```

If `IGNORED`, include this in the snapshot (it does not stop the recommendation):
```
⚠️  {pm_state_root} is gitignored — project state will not be committed. Add to .gitignore:
  !{pm_state_root}/
  !{pm_state_root}/**
```

### 4. Build health snapshot

Report to user:

**Active epics** (from `{pm_state_root}/active/epic-*/epic.yaml`):
- List each epic: key, title, current sprint, sprint status
- Flag stale locks: if `_lock.claimed_at` is older than `_lock.ttl_minutes`, mark as ⚠️ STALE LOCK

**Planned epics** (from `{pm_state_root}/planned/epic-*/epic.yaml`):
- Count them, and list any whose `depends_on` names an epic that is not yet `done` (those
  are blocked, not merely waiting). Every epic under `planned/` has `status: backlog` —
  that is the only status `pm-status.py` accepts there — so there is no status breakdown
  to print.

**Open issues** (from `{pm_issues_file}`):
- Count by severity: Critical, High, Medium, Low

**Plan status** (from `plan-output-meta.yaml`):
- `readiness`, `generated` timestamp, and the phase count — read `phase_count` when present;
  when it is absent the pointer predates that field, so fall back to the length of its legacy
  `phases:` list. Current pointers carry `phase_count` and no `phases:` list; do not read
  anything else per-phase from this file, and never open the snapshot just to count phases.
- If absent: note "No plan found"

### 5. Recommend next action

Section 2 has already terminated with its own recommendation on the legacy, multi-layout,
and orphan branches — this table is only reached when the sharded layout is the only one
present, or on a verified genuine first run. Apply the first matching rule:

| Condition | Recommendation |
|---|---|
| No state files, no epics (**only after section 2's first-run check passed**) | `Run bmad-create-epics-and-stories to create your project backlog first.` |
| No plan-output-meta.yaml | `Run /l3io-pm-plan to validate readiness and build the execution plan.` |
| plan readiness = red | `Run /l3io-pm-plan to resolve readiness gaps (readiness: red).` |
| plan readiness = amber | `Run /l3io-pm-plan to address readiness warnings (readiness: amber), or /l3io-pm-execute to proceed.` |
| Any epic has stale lock | `Epic {key} has a stale lock (claimed {N}m ago). Run: python3 {pm_status} clear-lock --state-root {pm_state_root} --epic {key}` |
| Active epic, no BLOCKED sprint | `Run /l3io-pm-execute {key} to continue the in-progress epic.` |
| No active epics, plan exists, planned epics available | `Run /l3io-pm-execute to start execution (plan is green).` |
| All epics done (active + planned = 0) | `All work complete. Run /l3io-pm-sync to push closure to GitHub/ADO.` |

**One more follow-up, checked after the table above:** if `{pm_status_present}` is `absent`
or `{pm_status_stale}` is `yes`, prepend it to the recommendation — this takes priority
because it explains a failure the user would otherwise hit with no clue why:
`pm-status.py is {missing | stale (installed {installed}, expected {expected})} at
{project-root}/_bmad/scripts/pm-status.py. Run /l3io-util-doctor first to install or refresh
it — {this report read epic.yaml directly instead | the command above may need a subcommand
the installed copy lacks}.`

Output the recommendation as a clear, one-paragraph response with the exact command to run.

### Progress Mode

Invoked with the `progress` argument. Read-only — `report` writes only when `--out` is
passed, and nothing here passes it.

**When `{pm_status_present}` is `absent`:** print this and stop. The report is the one thing
in this skill that genuinely needs the helper — it computes dwell times and phase roll-ups
that cannot be read off `epic.yaml`:

```
pm-status.py is not installed. Run /l3io-util-doctor to install it, then re-run
/l3io-pm-help progress.
```

**When `{pm_status_stale}` is `yes`:** do not stop — `report`'s output shape has been stable
across the versions this matters for — but print this first, then continue:

```
⚠️  pm-status.py at {project-root}/_bmad/scripts/pm-status.py is stale (installed
{installed}, this skill ships {expected}). Run /l3io-util-doctor to refresh it.
```

**Otherwise** run:

```bash
python3 {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format tree
```

**Scope — map what the user asked for to a `--status` filter.** The state tree's three
folders are the vocabulary: `planned` = backlog, `active` = in progress, `archived` = done.

| They asked for | Pass |
|---|---|
| nothing, "progress", "status" | *(nothing — defaults to planned + active)* |
| "what's active", "in flight", "what's running", "in progress", "what's moving" | `--status active` |
| "what's queued", "backlog", "not started", "what's next" | `--status planned` |
| "everything", "including done", "including archived", "all" | `--all` |

Counting is unaffected by the filter: totals and phase denominators always cover every epic,
so a narrowed view never changes what "2/3 epics done" means. When the filter is not the
default the report prints a `SHOWING …` banner itself — do not add your own caveat.

Print the output verbatim. Do not summarize it, re-order it, or re-format it into your own
table — it is already the rendered view, and paraphrasing it invites drift between what the
tool computed and what the user reads.

Then add one line pointing at the live view, because that is what answers "what is happening
right now" during a long run:

```
For a live view during a run: python3 {pm_status} report --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml --watch 15
```

Two follow-ups, only when the output warrants them:

- If the output contains `⚠ STALE LOCK`, append the clear-lock recommendation from section 5
  for each affected epic. Do not re-derive stale-lock state yourself — the report already
  computed it from `_lock.ttl_minutes`.
- If the output ends with the `~ dwell times are approximate` note, add: `Dwell times sharpen
  once state/events.jsonl accumulates transitions — it starts recording on the next
  /l3io-pm-execute run.`
