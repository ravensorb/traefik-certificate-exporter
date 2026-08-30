## Rename Active Mode

Invoked with `rename-active` argument. One-time migration for projects using the old
`sprint-status-active.yaml` filename. Renames the file to `sprint-status.yaml` so the PM
skills and the core BMad framework skills find the right file without overrides. Content is
not changed — placement only.

### Steps

**Step RA1 — Load config and check preconditions**

Load config (same as layout cleanup). Resolve paths:
- Old name: `{implementation_artifacts}/sprint-status-active.yaml`
- New name: `{implementation_artifacts}/sprint-status.yaml`

If `sprint-status-active.yaml` does NOT exist:
```
sprint-status-active.yaml not found at {implementation_artifacts} — nothing to rename.
```
Exit.

If `sprint-status.yaml` already exists:
```
Conflict: sprint-status.yaml already exists at {implementation_artifacts}. Cannot rename sprint-status-active.yaml — resolve manually (e.g. remove or merge the existing sprint-status.yaml first).
```
Exit.

**Step RA2 — Dry-run**

```
RENAME ACTIVE DRY RUN
Will rename: {implementation_artifacts}/sprint-status-active.yaml
         → {implementation_artifacts}/sprint-status.yaml
Content unchanged — filename only.
```

**Step RA3 — Confirm**

Ask: "Rename sprint-status-active.yaml → sprint-status.yaml?"

If no: print `Rename cancelled — no changes made.` and exit.

**Step RA4 — Rename**

Rename `sprint-status-active.yaml` → `sprint-status.yaml`.

**Step RA5 — Verify**

Re-parse `sprint-status.yaml` as YAML to confirm the file is valid. Confirm the old name
`sprint-status-active.yaml` no longer exists at that path. If YAML parse fails, rename the
file back and print:
```
FAILED — sprint-status.yaml is not valid YAML after rename. Restored to sprint-status-active.yaml. Parse error: {error}
```

**Step RA6 — Report**

```
DONE — Renamed sprint-status-active.yaml → sprint-status.yaml. No content changed.
```

---
