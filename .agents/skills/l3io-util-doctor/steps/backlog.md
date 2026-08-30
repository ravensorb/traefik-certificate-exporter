## Backlog Mode

Invoked with `backlog` argument. Read-only — lists all items in the consolidated `backlog:` list from the issues file in a readable table grouped by severity. No files are changed.

### Steps

**Step BL1 — Load config and resolve the issues file**

Load config (same as layout cleanup). The backlog lives in `{pm_issues_file}`
(`{pm_state_root}/issues.yaml`) — the single flat deferred-issue list the current layout
uses, written by `pm-status.py append-issue`. If it does not exist, decide which case this is
using the layout detection from Check 2b:

- **A legacy layout is present** (legacy flat `sprint-status*.yaml`, or legacy per-epic
  `_bmad/state/`):
  ```
  No issues file at {pm_issues_file} — this project is still on a legacy state layout.
  Run /l3io-util-doctor migrate-state to migrate; the backlog is carried over as part of it.
  ```
- **The sharded tree exists but has no issues file yet**, or nothing exists at all:
  ```
  Backlog is empty — no issues file at {pm_issues_file} yet. It is created the first time a
  review defers an item.
  ```

Exit in either case.

**Step BL2 — Parse**

Read the top-level `backlog:` list. If the list is absent or empty, print `Backlog is empty — no items found.` and exit.

**Step BL3 — Print table**

Group items by severity (Critical → High → Medium → Low → unknown). Within each group, sort by `epic` ascending then `key` ascending. Print:

```
BACKLOG — {pm_issues_file}
================================================================
Sev      Key           Epic  Sprint  Title
----------------------------------------------------------------
Critical
  CRIT   BL-E001-001   001   02      {title (truncated to 50 chars)}
  ...
High
  HIGH   BL-E001-002   001   —       {title}
  ...
Medium
  MED    BL-E000-001   000   —       {title}
  ...
Low
  LOW    BL-E002-001   002   03      {title}
  ...
================================================================
Total: {n} item(s)  (Critical: {n}  High: {n}  Medium: {n}  Low: {n})
```

Truncate titles at 50 characters with `…`. Sprint shown as `—` when blank.

---
