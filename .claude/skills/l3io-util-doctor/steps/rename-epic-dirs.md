## Rename Epic Dirs Mode

Invoked with `rename-epic-dirs` argument. One-time-per-occurrence migration for epic artifact
directories still using the legacy two-digit form (`epic-{nn}/`). Renames each to the current
three-digit form (`epic-{nnn}/`) so it matches the epic key `E{nnn}` and its
`state/{status}/epic-{nnn}/` counterpart — the identical-path-suffix property the state/artifact
drift check (Health Check 11) depends on. Content is not changed — directory name only.

### Steps

**Step RE1 — Load config and scan**

Load config (same as layout cleanup). Scan the top level of `{implementation_artifacts}/` for
directories matching `epic-[0-9][0-9]` (exactly two digits).

If none found:
```
No legacy two-digit epic-{nn}/ directories found — nothing to rename.
```
Exit.

**Step RE2 — Dry-run**

For each matched directory, compute the three-digit destination by zero-padding the epic
number. If that destination already exists, record a conflict instead of a rename (skip it;
never overwrite).

```
RENAME EPIC DIRS DRY RUN
================================================================
{implementation_artifacts}/epic-{nn}/  →  {implementation_artifacts}/epic-{nnn}/
...
================================================================
{N} director(y/ies) to rename, {C} conflict(s) (destination already exists — skipped).
Contents unchanged — directory name only.
```

If `{N}` is 0 (all conflicts): print the conflict list and exit without prompting.

**Step RE3 — Confirm**

Ask: "Rename {N} epic director(y/ies) to the three-digit form? Conflicts are skipped."

If no: print `Rename cancelled — no changes made.` and exit.

**Step RE4 — Rename**

For each non-conflicting directory, rename `epic-{nn}/` → `epic-{nnn}/`. Log each rename.

**Step RE5 — Verify**

Re-scan `{implementation_artifacts}/` top level. Confirm no `epic-[0-9][0-9]` (two-digit)
directories remain except recorded conflicts.

**Step RE6 — Report**

```
DONE — Rename epic dirs complete.
  Renamed:   {n} director(y/ies)
  Conflicts: {n} (destination already existed — left in place; list if > 0)
```

If conflicts remain, note that they need manual resolution (merge or remove one side) before
Health Check 11's drift comparison can be trusted for that epic.

---
