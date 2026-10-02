### 2. Detect state layout — before reading anything, and before any recommendation

**This section gates every rule in section 5.** l3io-help is the command an upgrading user
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
/l3io-doctor migrate-state.
```

**If only the legacy per-epic layout or only the legacy flat layout** → stop here. Report
what was found and give exactly one recommendation:

```
⚠️  Legacy state layout detected (legacy per-epic layout = _bmad/state/, legacy flat layout
= flat sprint-status.yaml). Your project has existing l3io-pm state in a layout the current
skills no longer read.

Next action:  /l3io-doctor migrate-state

Nothing else should run first. The migration is non-destructive until its final stage and
keeps your originals as .legacy backups.
```

Never recommend `bmad-create-epics-and-stories`, `/l3io-plan`, or `/l3io-execute` on
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

If both print nothing → genuine first run. Continue to section 3; rule 1 in section 5 may
now fire safely.

This orphan check is duplicated in `l3io-doctor`'s `steps/stats.md` Step ST1 — a
cross-skill duplication with no mechanical guard, needed because `progress` no longer loads
this file and forwards to `stats` instead. Keep both in sync if the paths or wording change.

