## Schema Migration Mode

Invoked with `migrate-schema` argument. Upgrades an existing `sprint-status.yaml` to the current field schema. Adds missing fields with zero/empty defaults. Never overwrites existing non-null values. Never guesses at values — only mechanical defaults (zero for numbers, empty for strings, `'unknown'` for enums).

**Two field types are not mechanically defaultable, and this mode must not invent them:**

- **`cost` is derived, never entered** — `cost = tokens_k × the model's per-class rates` (the l3io-pm metrics contract; the PM skills carry it as `references/metrics-contract.md` §2). `set-actual`/`set-estimate` reject a `--cost*` flag outright, and `verify` recomputes it and fails on a mismatch. So `cost_low`/`cost_high` are **never added to an estimate block** by this migration: nothing verifies an estimate, and a placeholder is worse than an absence. The old `'$0.00'` default was doubly wrong — a currency-prefixed *string* where every writer produces an unquoted float.
- **`tokens_k` and `cost` on an `actual` block default to the `'N/A'` sentinel, not `0`.** A legacy flat file has no token data. `0` claims a measurement that was never taken, and calibration would consume it as a real sample and drive the learned ratio toward zero; `'N/A'` is skipped by calibration and passes `verify --runtime other`, which is the honest state of a legacy migration.

### Default Values for Missing Fields

| Field type | Default |
|---|---|
| Numeric (`elapsed_hours_low/high`, `hitl_hours_low/high`, `man_hours_low/high`, `tokens_k_min/max`, `elapsed_hours`, `man_hours`, `hitl_hours`, `fix_iterations`, `files_changed`) | `0` |
| `completion_evidence.tests_passing` | **Never added.** Derived (`DERIVED_NODE_FIELDS` in `pm-status.py`) from `completion_evidence.test_runs` — a legacy node with no recorded test runs correctly has no `tests_passing` key. If the legacy node already has a `tests_passing` value, preserve it as-is (`BOOL_NODE_FIELDS` still reads it) — never touch or retype it. |
| `tokens_k` / `cost` on an **actual** block | `'N/A'` — the sentinel, never `0` |
| `cost`, `cost_low`, `cost_high` on an **estimate** block | **never added** |
| `classification` enum | `'unknown'` |
| `severity` enum | `'unknown'` |
| `source`, `description`, `goal` | `''` |
| Epic/sprint `title` | Derived mechanically: `'Epic {id}'` / `'Sprint {id}'` |
| `bugs_fixed` list | Omit block entirely when `fix_iterations` defaults to `0` |
| `closed`, `retrospective` | Omit — only present when the actual value is known |

### Migration Steps

**Step M1 — Load config and locate status files**

Load config (same as layout cleanup). Detect which layout is present:

1. If `{implementation_artifacts}/sprint-status-backlog.yaml` OR `{implementation_artifacts}/sprint-status-archived.yaml` exists → **split layout**: bind `{status_files}` to all present split files: `sprint-status.yaml`, `sprint-status-backlog.yaml`, `sprint-status-archived.yaml` (include only those that exist; also include `sprint-status-active.yaml` if present and `sprint-status.yaml` is absent, for backward compatibility).
2. Else if `{implementation_artifacts}/sprint-status.yaml` exists → **legacy single-file**: bind `{status_files}` = `[ sprint-status.yaml ]`.
3. Else: print `No status files found at {implementation_artifacts} — nothing to migrate.` and exit.

Steps M2–M7 operate on each file in `{status_files}`. The dry-run table (Step M3) groups all files; confirmation (Step M4) covers all at once.

**Step M2 — Analyze**

Parse each file in `{status_files}`. For each node — epic, sprint, story, backlog item — collect every field that is absent from the current schema. Build a change list: file + node path + field name + proposed default value.

Schema fields to verify (add if absent):

*Epic node:*
- `title` (derive: `'Epic {id}'`)
- `goal`
- `estimate` block: `man_hours_low`, `man_hours_high`, `hitl_hours_low`, `hitl_hours_high`, `elapsed_hours_low`, `elapsed_hours_high`, `tokens_k_min`, `tokens_k_max`
- `actual` block (only when `status: done`): `elapsed_hours`, `man_hours`, `hitl_hours`, `tokens_k`, `cost`

*Sprint node:*
- `title` (derive: `'Sprint {id}'`)
- `estimate` block: `man_hours_low`, `man_hours_high`, `hitl_hours_low`, `hitl_hours_high`, `elapsed_hours_low`, `elapsed_hours_high`, `tokens_k_min`, `tokens_k_max`
- `actual` block (only when `status: done`): `elapsed_hours`, `man_hours`, `hitl_hours`, `tokens_k`, `cost`

*Story node:*
- `title` (derive from story `.md` file's first heading if the file exists; otherwise `''`)
- `classification`
- `completion_evidence` block (only when `status: done`): `fix_iterations`, `files_changed`. `tests_passing` is derived, not added — see the Default Values table above; if the legacy node already carries a `tests_passing` value, leave it exactly as-is, do not add one if it is absent.

*Backlog item node:*
- `source` (verify/add if absent)
- `severity` (verify/add if absent)
- `description` (verify/add if absent)

**Step M3 — Dry-run table**

```
SCHEMA MIGRATION DRY RUN — {status_files}
================================================================
File                          Node                              Field                Value
----------------------------------------------------------------
sprint-status.yaml            epics[01]                         title                'Epic 01'
sprint-status.yaml            epics[01]                         goal                 ''
sprint-status.yaml            epics[01]                         estimate.elapsed_hours_low  0
sprint-status.yaml            epics[01].sprints[01]             title                'Sprint 01'
sprint-status.yaml            epics[01].sprints[01].stories[ST01]  classification    'unknown'
sprint-status-backlog.yaml    epics[02].backlog[BL-01]          source               ''
...
================================================================
Summary: {field_count} fields to add across {epic_count} epics,
         {sprint_count} sprints, {story_count} stories, {backlog_count} backlog items
         ({file_count} file(s) affected)
No existing values will be changed.
```

If `{field_count}` is 0 across all files: print `Status files are already current — no fields to add.` and exit.

**Step M4 — Confirm**

Ask: "Proceed with schema migration? Existing values will not be changed."

If no: print `Migration cancelled — no changes made.` and exit.

**Step M5 — Write**

Apply all changes to each file in `{status_files}`. Preserve the existing field order within each node; append new fields after existing ones in their parent node. New blocks (`estimate`, `actual`, `completion_evidence`) are appended as a whole after existing peer fields.

**Step M6 — Verify**

Re-parse each written file in `{status_files}` as YAML. If any file fails to parse, restore its original content and print:
```
FAILED — {file} is not valid YAML. Original restored. Parse error: {error}
```

**Step M7 — Report**

```
DONE — Schema migration complete.
  Fields added: {field_count}
  Files: {status_files}
```

---
