## Clean Legacy Mode

Invoked with `clean-legacy` argument. Removes migration backup files *and directories* left
behind by one-time migration commands: `.yaml.legacy` files, `.v1` calibration backups, the
pre-migration `state.legacy/` directory and `pm-calibration.yaml.legacy` file `migrate-state`
Stage D leaves at their original `_bmad/` location, and the `migration-backup/` directory
Stage F's default "move" option relocates everything into. Dry-run first; confirms before
deleting. Safe to run once migrations have been verified.

### Steps

**Step CL1 — Load config and scan**

Load config (same as layout cleanup). Scan for:
1. `*.yaml.legacy` files anywhere under `{implementation_artifacts}/` (e.g.,
   `sprint-status.yaml.legacy`, `sprint-status-backlog.yaml.legacy`,
   `sprint-status-archived.yaml.legacy`) — `migrate-state` Stage D's per-file backups,
   present here when the F2 backup disposal chose "K" (keep in place) or has not run yet.
2. `*.yaml.v1` files in `{project-root}/_bmad/` (e.g., `pm-calibration.yaml.v1`) —
   `migrate-schema`'s field-upgrade backups.
3. `{project-root}/_bmad/pm-calibration.yaml.legacy` (file) — `migrate-state` Stage D's
   pre-migration calibration backup, at its original location.
4. `{project-root}/_bmad/state.legacy/` (directory) — `migrate-state` Stage D's whole-tree
   backup of a legacy per-epic `_bmad/state/` source, at its original location.
5. `{project-root}/_bmad/migration-backup/` (directory) — `migrate-state` Stage F2's default
   "move" destination. When present it already holds copies of some/all of items 1, 3, and 4
   (the flat `.legacy` files, `pm-calibration.yaml.legacy`, and `state.legacy/`), relocated
   there in one pass by F2. Treat it as a single item in the scan and report — do not also
   descend into it and list its contents as separate items. Items 1/3/4 above only match
   files/directories at their *original* `_bmad/`-or-`{implementation_artifacts}/` locations,
   so there is no double-counting: a repo that ran F2 with "M" has items 1/3/4 empty and item
   5 present; a repo that chose "K" has items 1/3/4 present and item 5 absent.

If nothing found: print `No legacy backup files or directories found — nothing to clean.` and exit.

**Step CL2 — Dry-run**

For each plain file, get its size (`stat`/`du -h`). For each directory (items 4 and 5), get
its total recursive size (`du -sh`) and a one-line content summary — top-level entry names
plus a recursive file count — so the user sees what is inside *before* agreeing to remove it:

```
CLEAN LEGACY DRY RUN
================================================================
File / Directory                                         Size     Contents
----------------------------------------------------------------
{implementation_artifacts}/sprint-status.yaml.legacy      {size}   —
{project-root}/_bmad/pm-calibration.yaml.v1                {size}   —
{project-root}/_bmad/pm-calibration.yaml.legacy             {size}   —
{project-root}/_bmad/state.legacy/                          {size}   DIR — {n} files (epic-001/, epic-002/, ...)
{project-root}/_bmad/migration-backup/                       {size}   DIR — {n} files (sprint-status.yaml.legacy, state.legacy/, pm-calibration.yaml.legacy)
...
================================================================
{N} file(s) and {M} director(y/ies) to remove. These are migration backups — the live files
are unaffected.
```

**Step CL3 — Confirm**

Ask: "Remove {N} backup file(s) and {M} backup director(y/ies)? This cannot be undone."

If no: print `Clean cancelled — nothing removed.` and exit.

**Step CL4 — Delete**

Delete each file with `rm -f`. Remove each directory with `rm -rf` **only after** its
contents were shown in the Step CL2 dry-run and the user confirmed in Step CL3 — never
remove a directory whose contents the user has not seen. Log each removal individually. If
any removal fails (permissions, locked file), record and continue — do not abort the entire
run.

**Step CL5 — Report**

```
DONE — Clean legacy complete.
  Removed: {n} file(s), {m} director(y/ies)
  Failed:  {n} file(s)/director(y/ies) (list if > 0)
```

---
