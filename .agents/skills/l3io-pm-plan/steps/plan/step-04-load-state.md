# Step 04: Load State

Communicate all responses in `{communication_language}`.

Reads all state files and builds the full in-scope index. Subsequent steps consume
`{epic_index}` and `{story_index}` directly — do not re-read state files.

---

## 1. Read active epics

List all epic directories under `active/`:

```bash
ls -d {pm_state_root}/active/epic-*/ 2>/dev/null || echo "(none)"
```

For each epic directory, read `epic.yaml` and extract:
- `key` (the epic key)
- `status` (always `in-progress` under `active/`)
- `depends_on` (list; empty if absent)
- `estimate` (present/absent)
- `_lock` (present/absent — flag locked epics)

List its `sprint-*/` subdirectories; for each, read `sprint.yaml` (`key`, `status`, `estimate`)
and its story `.yaml` files excluding `sprint.yaml` (`key`, `status`, `classification`,
`estimate`, `depends_on`). `python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key}`
gives the same sprint/story enumeration as a computed roll-up if you prefer reading that over
walking the directory by hand.

Record: `{active_epics}` = list of epic keys from `active/`.

## 2. Read planned epics

List all epic directories under `planned/` the same way:

```bash
ls -d {pm_state_root}/planned/epic-*/ 2>/dev/null || echo "(none)"
```

For each, read `epic.yaml` (`key`, `status` — always `backlog` under `planned/`, `depends_on`,
`estimate`) and its sprint/story subtree exactly as in section 1.

Record: `{backlog_epics}` = epics with `status: backlog` (all epics under `planned/`).

## 3. Read archived epic keys

List epic directories under `archived/` (may not exist yet):

```bash
ls -d {pm_state_root}/archived/epic-*/ 2>/dev/null || echo "(none)"
```

Extract just the epic key from each directory name (`epic-001` → `E001`). Store as
`{archived_epic_keys}`. Do not load full content — only the keys are needed to validate
`depends_on` references.

If the directory does not exist, `{archived_epic_keys}` = [].

## 4. Build epic index

Construct `{epic_index}` as a mapping from epic key to:
```
{
  "E001": {
    "status": "in-progress",
    "depends_on": [],
    "estimate_present": true,
    "locked": false
  },
  "E003": {
    "status": "backlog",
    "depends_on": ["E001", "E002"],
    "estimate_present": false,
    "locked": false
  }
}
```

## 5. Build story index

Construct `{story_index}` as a mapping from story key to:
```
{
  "E001-S01-001": {
    "epic": "E001",
    "sprint": "S01",
    "status": "done",
    "classification": "standard",
    "estimate_present": true,
    "depends_on": []
  }
}
```

## 6. Report index summary

```
State loaded:
  Active epics:   {active_epic_count} ({active_epic_keys joined by comma})
  Backlog epics:  {backlog_epic_count}
  Archived epics: {archived_epic_count}
  Stories in scope: {total_story_count}
  Locked epics: {locked_count} (warning if any)
```

If any locked epic is found:
```
⚠️  {epic_key} is locked by session {session_id} (claimed {claimed_at}, TTL {ttl_minutes}m).
    Run: pm-status.py check-lock --state-root {pm_state_root} --epic {epic_key} --session-id {your_session_id}
    to verify if the lock is stale. Clear with: pm-status.py clear-lock --state-root {pm_state_root} --epic {epic_key}
```

## 7. Output status line

```
Step 04 complete — epics: {total_epic_count} ({active_count} active, {backlog_count} backlog), stories: {total_story_count}
```
