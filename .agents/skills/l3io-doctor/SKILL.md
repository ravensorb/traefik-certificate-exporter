---
name: l3io-doctor
description: Migration and housekeeping utilities for BMad artifacts and l3io-pm state. Use when the user needs to migrate a legacy state layout (flat sprint-status.yaml, or legacy per-epic _bmad/state/) to the current sharded state tree, bootstrap sharded state nodes from existing story .md artifact files (for stories created outside l3io-plan), reorganize legacy flat artifact outputs into the structured epic/sprint folder layout, harvest deferred-shortcut code markers into the issues backlog, validate zero-padded naming in the state tree, review the issues backlog or a plan-aware progress dashboard, triage the backlog (audit and close what is already fixed), move ADRs from the old per-epic home to docs/adr/, or update AI system instruction files to describe the current state layout. Also carries older legacy-only bridging modes (migrate-schema, split-status, reconcile-status) for repos that have not yet migrated. Run without arguments for an auto-diagnostic that scans project state and proposes the right actions.
---

# l3io-doctor — Project State Diagnostics & Utilities

## Overview

Migration and housekeeping utilities for BMad artifacts.

**Default behavior (no argument, or text matching no keyword below):** Runs a project health check — scans for all known issues, reports findings in a priority table, and proposes the right actions in the correct execution order. One confirmation runs them all.

**A REMOVED keyword is refused by name, never treated as unrecognized text.** Check the
argument against this table *before* falling through to the health check. Print the
replacement and stop; propose nothing.

- Removed **normalize** → `sort-status` for the naming report; on a legacy split layout
  also `reconcile-status`. Those two are all it ever ran.
- Removed **rename-active** → just `/l3io-doctor`; Health Check 1 detects the old
  filename and renames it inline.
- Removed **rename-epic-dirs** → just `/l3io-doctor`; Health Check 10 detects two-digit
  `epic-{nn}/` directories and renames them inline.
- Removed **overlay** → nothing yet; held back until `assets/overlays/` ships overlay TOML.
- Removed **cleanup** → the skill was renamed; use `/l3io-doctor`.

> Deliberately a list and **not a table**, and the removed names are bold rather than
> code-formatted. `DOCTOR_ROUTING_ROW_RE` matches any SKILL.md table row whose first cell is
> backticked tokens, so writing this as a table added all five to the keyword set check 25
> derives — neutering the guard that catches a stale keyword. Its scope-attack test caught it.
> Keep this shape.

> Falling through meant someone typing a keyword that used to work got a health check and a
> proposal to write files they never asked about — the argument silently ignored. `backlog`
> and `issues` are deliberately NOT here: they are live aliases for `stats`.
>
> This table duplicates `docs/upgrading.md`'s removed-keyword mapping, which is the
> user-facing copy. **No check enforces that the two agree** — `check:module` rule 9 reads
> the Menu column of the routing table below, not this one. Stated rather than implied,
> per `CLAUDE.md` §3: if you remove a keyword, edit both.

Modes (pass as argument to skip directly to that mode):

**Diagnostic (read-only)**
- **`check` / `status`:** Read-only health check — same diagnostic scan as the default but prints the findings table and exits without prompting to make changes. The full set of findings, their severities, and their remedies is defined in `steps/health-check.md`, not repeated here.
- **`stats`** (aliases **`backlog`**, **`issues`**): Plan-aware progress dashboard — phase → epic → sprint → story hierarchy with per-status dwell times and stuck-item flags (via `pm-status.py report`), plus backlog size by severity, the per-item backlog table from `{pm_state_root}/issues.yaml` grouped by severity, last closed sprint/epic, and calibration state. Scope it by asking — "what's active", "what's queued", "everything" — which maps to `--status`; counting always covers every epic regardless. No files changed.
- **`check-deps`:** Verifies every BMad skill this package dispatches resolves in this project, reports deprecated shims still in use, and names optional dependencies whose phases will self-skip. No files changed.
- **`check-pm-status`:** Compares the installed `{project-root}/_bmad/scripts/pm-status.py` against this doctor's `module_version` and reports whether it is current, stale, or absent. Used by `pm-help` at activation to warn about a stale copy; also runnable directly. No files changed.
- **`version`** (aliases **`--version`**, **`which-version`**): Reports which l3io-extensions version this project is running, read from the manifests the installer writes — per skill and, for the four module homes, per module. Exits 3 on a tree carrying more than one version, which is a partial install. This is the mode that answers "which l3io am I on?"; `check-pm-status` answers the narrower question of whether the self-installed `pm-status.py` is current, and reports STALE for one invocation after a correct upgrade because the installer does not write that copy. No files changed.
- **`install`** (aliases **`upgrade`**, **`uninstall`**): Runs the right BMad command for the intent and refuses the wrong one. `upgrade` uses `--action quick-update`, which derives the module set and IDE list off the existing install and deletes nothing; `install` is first-install only and refuses an existing install, because its `--modules`/`--tools` are authoritative and BMad deletes every module and IDE tree they do not name without confirming; `clean` removes only this extension's payload, decided by SHA-256 against each skill's `payload-manifest.json`, keeping any file a user has edited and never touching project state. Confirms before every action; `clean` is a dry run until `--apply`.

**One-time migrations (run in this order)**
- **`migrate-schema`:** *(legacy-only)* Upgrades an existing legacy flat `sprint-status.yaml` to the current field schema — adds missing fields with zero/empty defaults, never overwrites existing values.
- **`split-status`:** *(legacy-only)* Splits a legacy flat `sprint-status.yaml` into the three-file `sprint-status{,-backlog,-archived}.yaml` form, partitioning every epic/sprint by status. The PM skills do **not** read these files — this is an intermediate shape that lets `reconcile-status` clean up a messy flat file before `migrate-state` consumes it. One-time; the original is preserved as `sprint-status.yaml.legacy`.
- **`migrate-state`:** Migrates from either legacy layout (flat `sprint-status*.yaml`, or legacy per-epic `_bmad/state/`) to the sharded state tree under `{implementation_artifacts}/state/`. Preserves originals as `.legacy` files.
- **`bootstrap-state`:** Creates sharded state YAML nodes from existing story `.md` artifact files — for projects whose stories were created via the legacy `bmad-create-story` workflow (or another) outside of `l3io-plan`. Never overwrites existing state nodes (additive and safe to repeat). After bootstrap, run `/l3io-plan` or `/l3io-execute` normally.
- **`migrate-adrs`:** Moves ADRs from the old per-epic home (`{implementation_artifacts}/epic-*/arch/`) to `{project-root}/docs/adr/`, renumbering a colliding one only inside its own epic's artifacts; plans first, confirms, commits once.

**Ongoing maintenance (safe to repeat)**
- **`reconcile-status`:** *(legacy-only)* Audits the three split status files for placement and structure issues: epics in the wrong file for their `status`, nested per-epic `backlog:` arrays that should be flattened into the consolidated top-level list, stale backlog items whose status is no longer `backlog`, and empty epic shells in the backlog file. Dry-run first; confirms before writing. Safe to run at any time.
- **`sort-status`:** Validates state file and directory naming against the zero-padded convention (`epic-{nnn}/`, `sprint-{nn}/`, `E{nnn}-S{nn}-{nnn}.yaml`). Ordering itself can no longer drift under the sharded layout — directory listing order is correct order — so this mode no longer reorders anything. It reports misnamed entries, which would sort incorrectly and break key resolution.
- **`clean-layout`** (alias `layout-cleanup`): Runs only the artifact layout reorganization (the original default behavior) — reorganizes flat artifact outputs into the structured epic/sprint folder hierarchy, reconciles references, verifies state consistency.
- **`redrive`:** Rebuilds the `scope` and `fix` calibration components from the story nodes on disk — repairs samples poisoned by a fixed defect where `fix_iterations` was once stored as a string and misclassified as `backout` instead of `exact`. Backs up the calibration file first (only if no backup already exists); `closure`, `orchestration`, and `token_mix` are untouched. Safe to run repeatedly — it derives fresh from the same nodes each time.
- **`triage`:** Audits the issues backlog — integrity (`audit-issues`), mechanical evidence (`scripts/audit-backlog.py`), and an optional agent review — and resolves what is already fixed, with evidence, only on confirmation.

**Source & external sync**
- **`harvest-debt`:** Greps the whole source tree for `bmad-defer:` deferred-shortcut markers (the comment crumbs developers and dev subagents leave when they take an intentional simplification) and harvests them into the consolidated `backlog:` list so deferrals do not rot into "later means never." Language-generic — recognizes the comment syntax of every common language. Re-runnable: dedupes against already-harvested markers. Report-only by default; backlog merge is confirmed. Respects `harvest_exclude_dirs` in the `l3io-util` config section for additional exclusions beyond the built-in list.
- **`update-ai-rules`:** Scans for AI system instruction files in the project (`CLAUDE.md`, `.github/copilot-instructions.md`, `GEMINI.md`, `AGENTS.md`, `.cursorrules`, and others) and rewrites any reference to a legacy state layout (flat `sprint-status*.yaml`, the three-file split, or `_bmad/state/`) to describe the current sharded state tree. For files that already exist: updates existing references. For the currently running AI system's file if it does not exist: creates it with a state layout section. Never creates files for other AI systems. Also auto-invoked after a successful `split-status` run. Safe to run repeatedly.

**Setup & housekeeping**
- **`clean-legacy`:** Removes migration backup files and directories left behind by one-time migration commands — `.yaml.legacy` files, the `{pm_calibration_file}.v1` calibration schema backup in the state root, the pre-migration `_bmad/state.legacy/` directory and `_bmad/pm-calibration.yaml.legacy` file, and the `_bmad/migration-backup/` directory `migrate-state` Stage F's default "move" option relocates everything into. Dry-run first; confirms before deleting. Safe to run once migrations have been verified.

**One-time use (layout cleanup):** Designed to be run once per project. Running again after a successful cleanup produces zero moves (everything already placed) or conflicts (for new flat files added since the first run).

## Conventions

- `{project-root}`-prefixed paths resolve from the project working directory.
- `{skill-name}` resolves to the skill directory's basename.

## On Activation

**Load exactly one mode file.** Every mode below lives in its own file under `steps/`, and
only the one the argument selects is ever loaded. That is the point of the layout: this skill
carries nineteen procedures and a run needs one, so inlining them all charged every
invocation for eighteen it would not execute. Read this file, match the keyword, load that
one file, and follow it.

**Recognized keywords** — if the user's argument exactly matches any of these, load that
file and follow it:

The **Menu** column records whether that keyword carries its own row in
`assets/module-help.csv`, and is the source of truth for that decision — it is not kept
anywhere else; `check:module` rule 9 reads this column and fails on a keyword that is
neither registered nor excluded here, so an unrecognized value fails rather than quietly
excluding a mode. `registered` means it has a row whose `action` column is the keyword.
`default` means it is served by the module's bare-invocation row — the one with an empty
`action`, which is BMad's convention for a default invocation. `health-check` means it
deliberately does not: Step HC6 of `steps/health-check.md` already proposes it and fixes its place in the
execution order, so a global menu entry would invite running a migration or a repair
*without* the diagnosis that decides whether it is needed. `not-a-capability` is help output
or module setup.

| Keyword | Load | Menu | Notes |
|---|---|---|---|
| `help` or `?` | — | not-a-capability | Print the command list below and exit — no project scan. |
| `check` or `status` | `steps/health-check.md` | default | read-only — scan only, no changes |
| `stats`, `backlog` or `issues` | `steps/stats.md` | registered | read-only — plan-aware progress dashboard plus the per-item backlog table |
| `check-deps` | `steps/check-deps.md` | registered | read-only — verify BMad skill dependencies resolve |
| `check-pm-status` | `steps/check-pm-status.md` | registered | read-only — verify the installed pm-status.py matches this doctor's module_version |
| `version`, `--version` or `which-version` | `steps/version.md` | registered | read-only — report the installed l3io-extensions version per skill and per module |
| `install`, `upgrade` or `uninstall` | `steps/install.md` | registered | runs BMad's installer (`upgrade`/`install`) or deletes this extension's payload (`clean`) — every path confirms first; `clean` reports before it changes anything |
| `clean-layout` or `layout-cleanup` | `steps/clean-layout.md` | health-check | layout reorganization only. `clean-layout` is the primary; `layout-cleanup` is the DEPRECATED alias from ≤ 3.1.3, kept so old muscle memory still routes. Verb-first (`clean-<noun>`) mirrors `clean-legacy`. |
| `migrate-schema` | `steps/schema-migration.md` | health-check | legacy-only bridge |
| `split-status` | `steps/split-status.md` | health-check | legacy-only bridge |
| `harvest-debt` | `steps/harvest-debt.md` | health-check |  |
| `reconcile-status` | `steps/reconcile-status.md` | health-check |  |
| `sort-status` | `steps/sort-status.md` | health-check |  |
| `redrive` | `steps/redrive.md` | health-check | rebuild calibration `scope`/`fix` from story nodes |
| `triage` | `steps/triage.md` | health-check | audit the backlog and resolve findings already fixed — confirms every write |
| `migrate-adrs` | `steps/migrate-adrs.md` | health-check | move ADRs from the old per-epic home to `docs/adr/` — confirms before writing |
| `update-ai-rules` | `steps/update-ai-rules.md` | health-check |  |
| `clean-legacy` | `steps/clean-legacy.md` | health-check | remove migration backup files |
| `migrate-state` | `steps/migrate-state.md` | health-check | prose around `migrate-engine.py` — confirms before and interprets after the eight-step migration run |
| `bootstrap-state` | `steps/bootstrap-state.md` | health-check | prose around `migrate-engine.py` with `read-artifacts.py` — creates state nodes from story `.md` files without overwriting existing nodes |
| `setup` or `configure` | `assets/module-setup.md` | not-a-capability | then continue to `steps/health-check.md`. **`install` is deliberately not here** — it routes to `steps/install.md`, because a user typing it means the extension, not this module's config. It was in both rows until 3.2.5, with no precedence rule to separate them. |

**Everything else** (no argument, unrecognized text, or a natural-language description) →
load `steps/health-check.md`.

A mode file may direct you to another mode's file — the health check proposes fixes by
naming the modes that apply. Load each as you reach it; do not pre-load the set. Three
proposed actions are **not** modes and have no file — `rename-active`, `rename-epic-dirs` and
`untrack-locks`: each is a single rename or `git rm --cached` with no caller outside the check
that detects it, and `steps/health-check.md` runs all three inline.


**Help output** — when `help` or `?` is passed, print the contents of
`assets/help-text.md` verbatim inside a code fence and exit. Load that file only when this
keyword selects it; SKILL.md carries just this pointer, not the 40-line output.

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
explicitly passes `setup` or `configure`.

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

Bind `{spec_align}` = `uv run {skill-root}/scripts/spec-align.py --project-root {project-root} --planning-root {planning_artifacts} --impl-root {implementation_artifacts} --state-root {pm_state_root} --pm-status {pm_status}`
for health Checks 15–19, triage's spec pass and `migrate-adrs`. It passes no `--spec-paths`,
so it checks the spec set the project's spec index recorded (pm-execute's `spec_paths`).

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
├── issues.yaml             ← open BL-E{nnn}-{nnn} items + next: key allocator
├── issues-resolved.yaml    ← resolved BL items, with resolution
└── pm-calibration.yaml
```

- **An epic's directory lives in the folder named for its status.** Every status transition is a directory move, so `git log --follow` keeps working across it.
- **The directory structure replaces child lists** — `epic.yaml` has no `sprints:` key and `sprint.yaml` has no `stories:` key. Children are discovered by listing the directory.
- **State is written only by `pm-status.py`**, addressed by node key, never by hand-built path:
  `uv run _bmad/scripts/pm-status.py set-status --state-root {pm_state_root} --story E001-S01-003 --status done`
- Do not hand-edit these files, and do not create parallel status files.

Older layouts (a flat `sprint-status*.yaml`, or a per-epic `_bmad/state/` tree) are legacy. Migrate with `/l3io-doctor migrate-state`.
