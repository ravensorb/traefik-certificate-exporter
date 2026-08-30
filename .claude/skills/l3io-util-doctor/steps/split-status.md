## Split Status Mode

**Legacy-only mode — bridging step, not the current layout.**

Invoked with `split-status` argument. Splits a single legacy flat `sprint-status.yaml` into
the three-file `sprint-status{,-backlog,-archived}.yaml` layout. One-time, one-way. The
original is never deleted — it is renamed to `sprint-status.yaml.legacy` as the rollback.
All [Safety Rules](`SKILL.md` § Safety Rules) apply: dry-run first, never overwrite an existing
destination, preserve node contents exactly.

**The PM skills do not read or write these three files.** They read the sharded state tree
at `{pm_state_root}` and hard-block on any legacy layout (`references/status-files.md`
§10). The three-file split is an *intermediate* form on the way there: it is a convenient
shape for `reconcile-status` to clean up a messy flat file before `migrate-state` consumes
it, and `migrate-state` reads all three as one logical set. Nothing else consumes them.

Do not run this mode expecting it to make a project usable — `migrate-state` is what does
that. Run this only if you need `reconcile-status` on a legacy flat file first. On a project
that has already migrated there is nothing here to do; run `/l3io-util-doctor migrate-state`
or nothing at all.

### Target files

In `{implementation_artifacts}/`:
- `sprint-status.yaml` — `epics:` with `status: in-progress`.
- `sprint-status-backlog.yaml` — `epics:` = not-yet-started work; `backlog:` = consolidated deferred-issue list.
- `sprint-status-archived.yaml` — `epics:` with `status: done`.

### Placement rule (partition)

Granularity is **epic + sprint**; stories always travel inside their owning sprint node.

| Source node | Destination |
|---|---|
| Epic with `status: done` | `archived` — whole epic subtree, unchanged. |
| Epic with `status: in-progress` | `active` — epic node carrying only its `in-progress` and `done` sprints (with all their stories). |
| Backlog (not-yet-started) sprints of an in-progress epic | `backlog` — under an epic **shell** (`id`, `title`, `goal`, and a `sprints:` list of just those sprints). |
| Epic with `status: backlog` | `backlog` — whole epic subtree, unchanged. |
| Each item in any epic's nested `backlog:` array | `backlog` top-level `backlog:` list, flattened, each tagged with `epic:` (the owning epic id) and `sprint:` (the owning sprint id if the item names one, else `''`). |

A node lands in exactly one file. Files with no content are not written (a missing file is
treated as empty by the readers).

### Steps

**Step S1 — Load config and locate status file**

Load config (same as layout cleanup). Resolve `{status_file}` = `{implementation_artifacts}/sprint-status.yaml`. If absent, print:
```
sprint-status.yaml not found at {status_file} — nothing to split.
```
and exit. If any of the three target files already exists, print a conflict warning and exit
(the split has likely already been run); do not overwrite.

**Step S2 — Partition**

Parse `{status_file}`. Walk every epic, sprint, and nested `backlog:` array and assign each
node to `active`, `backlog`, or `archived` per the placement rule. Build the three in-memory
documents plus the flattened consolidated `backlog:` list.

**Step S3 — Dry-run table**

```
SPLIT STATUS DRY RUN — {status_file}
================================================================
Target file                       Epics  Sprints  Stories  Backlog
----------------------------------------------------------------
sprint-status.yaml                  {a_e}   {a_s}    {a_st}      —
sprint-status-backlog.yaml          {b_e}   {b_s}    {b_st}   {bl_count}
sprint-status-archived.yaml         {r_e}   {r_s}    {r_st}      —
================================================================
Original preserved as: sprint-status.yaml.legacy
No node contents are modified — placement only.
```

**Step S4 — Confirm**

Ask: "Proceed with the split? The original is kept as sprint-status.yaml.legacy."

If no: print `Split cancelled — no changes made.` and exit.

**Step S5 — Write**

Write each non-empty target document to its file. Then rename `{status_file}` →
`{status_file}.legacy` (rename, never delete).

**Step S6 — Verify**

Re-parse each written target file as YAML. Confirm every epic/sprint/story from the original
appears in exactly one target file and no node was dropped or duplicated. If any check fails,
restore by renaming `.legacy` back to `sprint-status.yaml`, remove the partial target files,
and print:
```
FAILED — {reason}. Original restored to sprint-status.yaml; target files removed.
```

**Step S7 — Report**

```
DONE — Split complete.
  Active:   {a_e} epics / {a_s} sprints / {a_st} stories
  Backlog:  {b_e} epics / {b_s} sprints / {b_st} stories / {bl_count} deferred items
  Archived: {r_e} epics / {r_s} sprints / {r_st} stories
  Original: {status_file}.legacy
```

**Step S8 — Post-split ordering note**

The split preserves each node's original order exactly — nothing is reordered during the
split, so if the source `sprint-status.yaml` was already out of order, that carries through
unchanged. `steps/sort-status.md` (Sort Status Mode) no longer covers this: it validates naming in
the sharded `{pm_state_root}` tree, not ordering in this split-file layout. There is no
automated ordering fix for the split layout; append to the report:
```
Ordering: preserved from source order (not validated — sort-status covers the sharded
  state/ layout only, not this split-file layout)
```

**Step S9 — AI Rules Update**

After the split (and optional sort), automatically run Step AR1 of `steps/update-ai-rules.md` (Update AI Rules Mode) to scan for AI instruction files that reference the old `sprint-status.yaml`. If any are found, display the findings and ask: "Update {N} AI instruction file reference(s) now?" If yes, proceed through Steps AR2–AR6. If no, print: `Run /l3io-util-doctor update-ai-rules to update AI instruction files later.` and exit.

---
