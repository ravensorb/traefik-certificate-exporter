## Reconcile Status Mode

Invoked with `reconcile-status` argument. Audits the three split status files for four categories of drift and fixes them in one confirmed pass. Dry-run first; confirms before any writes. Safe to run at any time — re-runnable with no side effects when everything is already correct.

### What it fixes

1. **Misplaced epics** — `sprint-status.yaml` is the home for all non-done epics regardless of status (in-progress, backlog, pending, deferred, not-started, or any other status). Only `status: done` epics belong in `sprint-status-archived.yaml`. The backlog file holds the flat deferred-issues list and epic shells only — no full epic nodes.
   - `status: done` epic found in `sprint-status.yaml` or `sprint-status-backlog.yaml` → move to `sprint-status-archived.yaml`
   - Any non-`done` epic (in-progress, backlog, pending, deferred, or any other status) found as a full epic node in `sprint-status-backlog.yaml` or `sprint-status-archived.yaml` → move to `sprint-status.yaml`

2. **Nested backlog arrays** — nested `backlog:` arrays inside epic nodes (the `epics[N].backlog:` key in any of the three files) must be flattened into the top-level `backlog:` list in `sprint-status-backlog.yaml`. New items are deduped against the existing list (by `source` field first, then by `key`). The per-epic nested `backlog:` key is removed from the epic node after the items are merged.

3. **Stale resolved/promoted items** — items in the top-level `backlog:` list of `sprint-status-backlog.yaml` with `status` other than `backlog` should not remain in the list. Per the schema contract, resolved and promoted items are removed immediately; this step catches any that were left behind.

4. **Empty epic shells** — an epic shell in `sprint-status-backlog.yaml` is a partial epic node (`id`, `title`, `goal`, `sprints:`) that tracks backlog sprints of an in-progress epic. If the shell's `sprints:` list is empty (or absent) AND the corresponding epic is already in `sprint-status.yaml` as `in-progress`, the shell is stale and should be removed.

### Steps

**Step RC1 — Load config and resolve status files**

Load config (same as layout cleanup). Check for the split layout:
- If neither `sprint-status-backlog.yaml` nor `sprint-status-archived.yaml` exists in `{implementation_artifacts}/`:
  ```
  No split layout found. Run /l3io-util-doctor split-status first, then re-run reconcile-status.
  ```
  Exit.

Bind `{status_active}` = `sprint-status.yaml`, `{status_backlog}` = `sprint-status-backlog.yaml`, `{status_archived}` = `sprint-status-archived.yaml`. Process only files that exist; treat absent files as empty.

**Step RC2 — Audit**

Parse all present files. Collect four finding sets:

**A — Misplaced epics**

For each epic node in each file, compare its `status` to the file it was found in. `sprint-status.yaml` is the home for **all non-done epics** regardless of status — in-progress, backlog, pending, deferred, not-started, or any other status. `sprint-status-backlog.yaml` holds shells and the flat deferred-issues list only; no full epic nodes belong there.

| File | Correct placement | Misplaced if |
|---|---|---|
| `sprint-status.yaml` | any epic with `status ≠ done` | has `status: done` → move to `sprint-status-archived.yaml` |
| `sprint-status-backlog.yaml` (full epic, not shell) | (no full epics belong here) | has any `status` field → move to `sprint-status.yaml` (unless `status: done`, then move to archived) |
| `sprint-status-archived.yaml` | `status: done` only | `status ≠ done` → move to `sprint-status.yaml` |

Note: epic shells in `sprint-status-backlog.yaml` (identified by having no `status` field — they carry only `id`, `title`, `goal`, and `sprints:`) are not misplaced epics; they are handled by finding set D.

Record each misplaced epic as `{ epic_id, title, current_status, current_file, correct_file }`.

**B — Nested backlog arrays**

For each epic node in all three files, check whether the node has a `backlog:` key (a per-epic nested backlog array). Collect every item in those arrays. For each item, check against the existing top-level `backlog:` list in `{status_backlog}`:
- Match by `source` field (same value → duplicate)
- If no `source`, match by `key` (same key → duplicate)
- Partition items into `new` and `duplicate`.

Record each finding as `{ epic_id, found_in_file, item_count, new_count, duplicate_count }`.

**C — Stale backlog items**

In the top-level `backlog:` list of `{status_backlog}`, collect every item where `status` is not `backlog`. Record each as `{ key, epic, title, current_status }`.

**D — Empty epic shells**

In `{status_backlog}`, identify epic nodes that are shells (no `status` field, has `sprints:` key). For each shell, check whether its `sprints:` list is empty or absent AND whether the corresponding epic id appears in `{status_active}` as `in-progress`. If both conditions are true, record as an empty shell `{ epic_id, title }`.

**Step RC3 — Dry-run report**

Print a consolidated findings table:

```
RECONCILE STATUS DRY RUN — {implementation_artifacts}
================================================================

A. Misplaced Epics: {A_count}
  Epic {id} "{title}" — status: {status} found in {current_file}
                      → move to {correct_file}
  ...

B. Nested Backlog Arrays: {B_total} item(s) across {B_epics} epic(s)
  {current_file} epics[{id}].backlog: {item_count} item(s) → flatten to top-level backlog:
    {new_count} new, {duplicate_count} duplicate(s) (skipped)
  ...

C. Stale Backlog Items: {C_count}
  {key} (status: {current_status}) — "{title}" → remove from backlog:
  ...

D. Empty Epic Shells: {D_count}
  Epic {id} shell in sprint-status-backlog.yaml — sprints: [] and epic is in-progress → remove shell
  ...

================================================================
Total changes: {total} across {file_count} file(s).
Nothing will be modified until confirmed.
```

If all four sets are empty:
```
✓ Status files are reconciled — no placement or backlog structure issues found.
```
Exit.

**Step RC4 — Confirm**

Ask: "Apply {total} reconciliation change(s) shown above?"

If no: print `Reconcile cancelled — no changes made.` and exit.

**Step RC5 — Execute**

Apply changes in this order to minimize intermediate invalid state. After each file write, re-parse as YAML; on any parse failure, restore that file's pre-reconcile content and print:
```
FAILED — {file} is not valid YAML after reconcile step {letter}. File restored. Remaining steps not applied.
```
Stop on any failure; do not apply further changes.

1. **A — Misplaced epics**: For each misplaced epic, read the full epic node from its current file, append it to the correct file (maintaining ascending `id` order within the `epics:` list), then remove it from the source file. Write both affected files.

2. **B — Nested backlog arrays**: For each epic node with a nested `backlog:` array, append the `new` items to the top-level `backlog:` list in `{status_backlog}`. Assign new keys for any item that lacks a `BL-E{epic}-{nn}` formatted key by continuing from the highest existing suffix for that epic (check all existing items in the top-level list with the same `epic` value). Remove the `backlog:` key from the epic node. Write `{status_backlog}` and the source file containing the epic node.

3. **C — Stale items**: Remove each stale item from the top-level `backlog:` list in `{status_backlog}`. Write `{status_backlog}`.

4. **D — Empty shells**: Remove each empty shell epic node from the `epics:` list in `{status_backlog}`. Write `{status_backlog}`.

**Step RC6 — Verify**

Re-parse all three files. Confirm:
- No epic appears in more than one file.
- Every epic's placement file matches its `status` (shells in `{status_backlog}` are exempt — they have no `status` field).
- No `epics[N].backlog:` keys remain in any file.
- No items with `status != backlog` remain in the top-level `backlog:` list.
- No empty shells remain in `{status_backlog}`.

If any check fails, list the remaining issues as warnings rather than errors (the file state is safe — the verify step is informational after a successful write).

**Step RC7 — Report**

```
DONE — Status reconciliation complete.
  Epics moved:              {A_count}  (to archived: {to_arch}, to active: {to_act}, to backlog: {to_bl})
  Backlog items flattened:  {B_new} new  ({B_dup} duplicate(s) skipped)
  Stale items removed:      {C_count}
  Empty shells removed:     {D_count}
  Files modified:           {file_list}
```

If `{A_count + B_new + C_count + D_count}` = 0 (nothing to do):
```
DONE — No reconciliation needed. Status files are already consistent.
```

---
