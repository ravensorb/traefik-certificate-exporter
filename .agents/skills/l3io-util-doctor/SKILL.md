---
name: l3io-util-doctor
description: Migration and housekeeping utilities for BMad artifacts and l3io-pm state. Use when the user needs to migrate a legacy state layout (flat sprint-status.yaml, or legacy per-epic _bmad/state/) to the current sharded state tree, reorganize legacy flat artifact outputs into the structured epic/sprint folder layout, harvest deferred-shortcut code markers into the issues backlog, validate zero-padded naming in the state tree, review the issues backlog or a plan-aware progress dashboard, or update AI system instruction files to describe the current state layout. Also carries older legacy-only bridging modes (migrate-schema, split-status, reconcile-status) for repos that have not yet migrated. Run without arguments for an auto-diagnostic that scans project state and proposes the right actions.
---

# l3io-util-doctor — Project State Diagnostics & Utilities

## Overview

Migration and housekeeping utilities for BMad artifacts.

**Default behavior (no argument or unrecognized text):** Runs a project health check — scans for all known issues, reports findings in a priority table, and proposes the right actions in the correct execution order. One confirmation runs them all.

Modes (pass as argument to skip directly to that mode):

**Diagnostic (read-only)**
- **`check` / `status`:** Read-only health check — same diagnostic scan as the default but prints the findings table and exits without prompting to make changes.
- **`stats`:** Plan-aware progress dashboard — phase → epic → sprint → story hierarchy with per-status dwell times and stuck-item flags (via `pm-status.py report`), plus backlog size by severity, last closed sprint/epic, and calibration state. Scope it by asking — "what's active", "what's queued", "everything" — which maps to `--status`; counting always covers every epic regardless. No files changed.
- **`backlog`:** Lists all items in the `backlog:` list of `{pm_state_root}/issues.yaml` in a readable table grouped by severity. No files changed.

**One-time migrations (run in this order)**
- **`migrate-schema`:** *(legacy-only)* Upgrades an existing legacy flat `sprint-status.yaml` to the current field schema — adds missing fields with zero/empty defaults, never overwrites existing values.
- **`split-status`:** *(legacy-only)* Splits a legacy flat `sprint-status.yaml` into the three-file `sprint-status{,-backlog,-archived}.yaml` form, partitioning every epic/sprint by status. The PM skills do **not** read these files — this is an intermediate shape that lets `reconcile-status` clean up a messy flat file before `migrate-state` consumes it. One-time; the original is preserved as `sprint-status.yaml.legacy`.
- **`migrate-state`:** Migrates from either legacy layout (flat `sprint-status*.yaml`, or legacy per-epic `_bmad/state/`) to the sharded state tree under `{implementation_artifacts}/state/`. Preserves originals as `.legacy` files.

**Ongoing maintenance (safe to repeat)**
- **`normalize`:** Convenience shortcut — runs `reconcile-status` then `sort-status` in one confirmed pass. Use for routine maintenance instead of running two commands separately.
- **`reconcile-status`:** *(legacy-only)* Audits the three split status files for placement and structure issues: epics in the wrong file for their `status`, nested per-epic `backlog:` arrays that should be flattened into the consolidated top-level list, stale backlog items whose status is no longer `backlog`, and empty epic shells in the backlog file. Dry-run first; confirms before writing. Safe to run at any time.
- **`sort-status`:** Validates state file and directory naming against the zero-padded convention (`epic-{nnn}/`, `sprint-{nn}/`, `E{nnn}-S{nn}-{nnn}.yaml`). Ordering itself can no longer drift under the sharded layout — directory listing order is correct order — so this mode no longer reorders anything. It reports misnamed entries, which would sort incorrectly and break key resolution.
- **`layout-cleanup`:** Runs only the artifact layout reorganization (the original default behavior) — reorganizes flat artifact outputs into the structured epic/sprint folder hierarchy, reconciles references, verifies state consistency.
- **`redrive`:** Rebuilds the `scope` and `fix` calibration components from the story nodes on disk — repairs samples poisoned by a fixed defect where `fix_iterations` was once stored as a string and misclassified as `backout` instead of `exact`. Backs up the calibration file first (only if no backup already exists); `closure`, `orchestration`, and `token_mix` are untouched. Safe to run repeatedly — it derives fresh from the same nodes each time.

**Source & external sync**
- **`harvest-debt`:** Greps the whole source tree for `bmad-defer:` deferred-shortcut markers (the comment crumbs developers and dev subagents leave when they take an intentional simplification) and harvests them into the consolidated `backlog:` list so deferrals do not rot into "later means never." Language-generic — recognizes the comment syntax of every common language. Re-runnable: dedupes against already-harvested markers. Report-only by default; backlog merge is confirmed. Respects `harvest_exclude_dirs` in the `l3io-util` config section for additional exclusions beyond the built-in list.
- **`update-ai-rules`:** Scans for AI system instruction files in the project (`CLAUDE.md`, `.github/copilot-instructions.md`, `GEMINI.md`, `AGENTS.md`, `.cursorrules`, and others) and rewrites any reference to a legacy state layout (flat `sprint-status*.yaml`, the three-file split, or `_bmad/state/`) to describe the current sharded state tree. For files that already exist: updates existing references. For the currently running AI system's file if it does not exist: creates it with a state layout section. Never creates files for other AI systems. Also auto-invoked after a successful `split-status` run. Safe to run repeatedly.

**Setup & housekeeping**
- **`clean-legacy`:** Removes migration backup files and directories left behind by one-time migration commands — `.yaml.legacy` files, `.v1` calibration backups, the pre-migration `_bmad/state.legacy/` directory and `_bmad/pm-calibration.yaml.legacy` file, and the `_bmad/migration-backup/` directory `migrate-state` Stage F's default "move" option relocates everything into. Dry-run first; confirms before deleting. Safe to run once migrations have been verified.
- **`rename-active`:** Renames `sprint-status-active.yaml` → `sprint-status.yaml`. Rarely needed directly — the health check detects and runs this automatically when the old naming is found.
- **`rename-epic-dirs`:** Renames legacy two-digit `epic-{nn}/` artifact directories to the current three-digit `epic-{nnn}/` form. Rarely needed directly — the health check detects and runs this automatically when the old naming is found.

**One-time use (layout cleanup):** Designed to be run once per project. Running again after a successful cleanup produces zero moves (everything already placed) or conflicts (for new flat files added since the first run).

## Conventions

- `{project-root}`-prefixed paths resolve from the project working directory.
- `{skill-name}` resolves to the skill directory's basename.

## On Activation

**Load exactly one mode file.** Every mode below lives in its own file under `steps/`, and
only the one the argument selects is ever loaded. That is the point of the layout: this skill
carries sixteen procedures and a run needs one, so inlining them all charged every
invocation for fifteen it would not execute. Read this file, match the keyword, load that
one file, and follow it.

**Recognized keywords** — if the user's argument exactly matches any of these, load that
file and follow it:

| Keyword | Load | Notes |
|---|---|---|
| `help` or `?` | — | Print the command list below and exit — no project scan. |
| `check` or `status` | `steps/health-check.md` | read-only — scan only, no changes |
| `stats` | `steps/stats.md` | read-only — plan-aware progress dashboard |
| `backlog` | `steps/backlog.md` | read-only — list consolidated backlog items |
| `normalize` | `steps/normalize.md` | reconcile-status then sort-status in one confirmed pass |
| `layout-cleanup` | `steps/layout-cleanup.md` | layout reorganization only |
| `migrate-schema` | `steps/schema-migration.md` | legacy-only bridge |
| `split-status` | `steps/split-status.md` | legacy-only bridge |
| `harvest-debt` | `steps/harvest-debt.md` |  |
| `reconcile-status` | `steps/reconcile-status.md` |  |
| `sort-status` | `steps/sort-status.md` |  |
| `redrive` | `steps/redrive.md` | rebuild calibration `scope`/`fix` from story nodes |
| `rename-active` | `steps/rename-active.md` |  |
| `rename-epic-dirs` | `steps/rename-epic-dirs.md` |  |
| `update-ai-rules` | `steps/update-ai-rules.md` |  |
| `clean-legacy` | `steps/clean-legacy.md` | remove migration backup files |
| `migrate-state` | `steps/migrate-state.md` | makes a legacy project usable by the PM skills again |
| `setup`, `configure`, `install` | `assets/module-setup.md` | then continue to `steps/health-check.md` |

**Everything else** (no argument, unrecognized text, or a natural-language description) →
load `steps/health-check.md`.

A mode file may direct you to another mode's file — `normalize` runs reconcile-status then
sort-status, and the health check proposes fixes by naming the modes that apply. Load each as
you reach it; do not pre-load the set.

**Help output** — when `help` or `?` is passed, print exactly this and exit:

```
l3io-util-doctor — Project State Diagnostics & Utilities
========================================================
Usage: /l3io-util-doctor [command]

Diagnostic (read-only)
  (no argument)      Project health check — scan and propose all needed actions
  check / status     Read-only health check — report findings, no changes
  stats              Plan-aware progress dashboard — phase/epic/sprint/story + backlog
  backlog            List issues.yaml backlog items grouped by severity

One-time migrations (run in this order)
  migrate-schema     (legacy-only) Add missing fields to a legacy flat sprint-status.yaml
  split-status       (legacy-only) Split flat sprint-status.yaml into the 3-file form
  migrate-state      Migrate either legacy layout to the sharded state tree  <- the one
                     that makes a legacy project usable by the PM skills again

Ongoing maintenance (safe to repeat)
  normalize          Reconcile then sort all status files in one pass
  reconcile-status   (legacy-only) Fix misplaced epics, nested backlogs, stale items
  sort-status        Validate zero-padded naming (epic-{nnn}/, sprint-{nn}/, story keys)
  layout-cleanup     Reorganize flat artifact files into epic/sprint folder structure
  redrive            Rebuild calibration scope/fix samples from the story nodes on disk

Source & external sync
  harvest-debt       Sweep source for bmad-defer: markers and harvest into backlog
  update-ai-rules    Update AI instruction files to describe the sharded state tree

Setup & housekeeping
  setup              Register l3io-util module config for this project
  clean-legacy       Remove .legacy/.v1 migration backup files and the state.legacy/ and
                     migration-backup/ backup directories after confirmation
  rename-active      (Rarely needed) Rename sprint-status-active.yaml → sprint-status.yaml;
                     the health check detects and runs this automatically when needed.
  rename-epic-dirs   (Rarely needed) Rename legacy epic-{nn}/ dirs to epic-{nnn}/; the health
                     check detects and runs this automatically when needed.

Run without arguments to let the health check decide what's needed.
```

Resolve config through BMad core's resolver — full contract in
`references/config-resolution.md`:

```bash
uv run --python 3.11 {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}
```

If the resolver is missing or fails, BMad core is not installed here — stop and tell the
user to run the BMad installer.

Bind, applying the default when the key is absent:

- `{output_folder}` — `core.output_folder` (default `{project-root}/_bmad-output`)
- `{implementation_artifacts}` — `modules.l3io-pm.implementation_artifacts`
  (default `{output_folder}/implementation-artifacts`)
- `{planning_artifacts}` — `modules.l3io-pm.planning_artifacts`
  (default `{output_folder}/planning-artifacts`)
- `harvest_exclude_dirs` — `modules.l3io-util.harvest_exclude_dirs` (default: none)

The artifact paths come from the **`l3io-pm`** section, not `l3io-util` — all modules share
one artifact tree, and this skill reorganizes the very directories the PM skills read.

An absent `modules.l3io-util` section is normal and is **not** a first-run trigger: this
module declares no required settings. Load `assets/module-setup.md` only when the user
explicitly passes `setup`, `configure`, or `install`.

Then bind the state paths every mode below uses (identical to the PM skills' bindings —
see `references/status-files.md` §10, the canonical contract):

- `{pm_state_root}` = `{implementation_artifacts}/state`
- `{pm_issues_file}` = `{pm_state_root}/issues.yaml`
- `{pm_calibration_file}` = `{pm_state_root}/pm-calibration.yaml`

**Install `pm-status.py` before dispatching to a mode** (skip this for `help`/`?` — that
keyword exits above without a project scan or any config resolve). This skill is the
documented post-upgrade entry point (`docs/upgrading.md`): a `quick-update` refreshes skill
payloads, and this skill is the very next step — so it cannot assume some other skill has
already refreshed the installed `pm-status.py`. Seven of the mode files below invoke
`{pm_status}`; a stale installed copy fails those calls with an opaque argparse error (a
missing `--key`, or `invalid choice` for a subcommand a newer payload added) rather than any
message that points at the real cause. Self-install compares the installed copy's **bytes**
against this skill's own copy and reinstalls on any difference; it refuses only to overwrite
a copy that is strictly *newer* than this skill's own, so running it here alongside the three
PM skills' self-installs is safe — whichever copy is newest wins, never a downgrade.

```bash
uv run {skill-root}/scripts/pm-status.py self-install \
  --dest {project-root}/_bmad/scripts/pm-status.py
```

If `uv` is unavailable, use `python3` instead. A "skipped — already up to date" message is
normal — that is the common case, not a problem. Failure here is BLOCKED.

Bind `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py` for use in all mode files
below.

**Current vs. legacy-only modes.** The sharded state tree under `{pm_state_root}` is the
layout the PM skills read and write today; they hard-block on anything else. Three modes
here — `migrate-schema`, `split-status`, `reconcile-status` — operate on the **legacy flat**
`sprint-status*.yaml` files only. They exist to bridge a repo that has not migrated yet, and
they are dead ends on a migrated repo. Where a mode is legacy-only it says so in its own
header; do not read those sections as descriptions of current behaviour.

## Safety Rules

- Dry-run first — show full cleanup plan before changing any files
- Never overwrite an existing destination file
- If destination exists: keep source in place, record conflict
- Preserve file contents exactly — move only, no edits
- Reference updates: auto-update only exact old-path matches that map to one known moved file; if ambiguous, record for manual review — never auto-update ambiguous references

## BMad PM — State File Layout

Epic, sprint, and story state lives in a **sharded state tree** under `{pm_state_root}`
(`{implementation_artifacts}/state/`) — one bare YAML file per node, committed to git:

```
state/
├── planned/epic-{nnn}/     ← status: backlog
├── active/epic-{nnn}/      ← status: in-progress
│   ├── epic.yaml
│   └── sprint-{nn}/
│       ├── sprint.yaml
│       └── E{nnn}-S{nn}-{nnn}.yaml
├── archived/epic-{nnn}/    ← status: done
├── issues.yaml             ← flat deferred-issue backlog (BL-E{nnn}-{nnn})
└── pm-calibration.yaml
```

- **An epic's directory lives in the folder named for its status.** Every status transition is a directory move, so `git log --follow` keeps working across it.
- **The directory structure replaces child lists** — `epic.yaml` has no `sprints:` key and `sprint.yaml` has no `stories:` key. Children are discovered by listing the directory.
- **State is written only by `pm-status.py`**, addressed by node key, never by hand-built path:
  `uv run _bmad/scripts/pm-status.py set-status --state-root {pm_state_root} --story E001-S01-003 --status done`
- Do not hand-edit these files, and do not create parallel status files.

Older layouts (a flat `sprint-status*.yaml`, or a per-epic `_bmad/state/` tree) are legacy. Migrate with `/l3io-util-doctor migrate-state`.
````

Adapt the heading style and surrounding content to match the existing file format for that AI system.

**Step AR6 — Verify and report**

Re-read each updated and created file. Confirm no legacy state reference (per the Detection rule — `sprint-status*.yaml`, `E{nnn}-status.yaml`, `_bmad/state/`, non-`.legacy`) remains. If any remain, list them as unresolved.

```
DONE — AI rules update complete.
  References updated: {N} across {M} file(s)
  Files created:      {C}
  Unresolved:         {U} (list if > 0)
  Files checked (no changes needed): {files}
```

---
