# Step 02: Readiness Check

Communicate all responses in `{communication_language}`.

Run after step-01-classify-work. Validates every story in scope before planning proceeds.
Bind `{readiness}` to the gate result before loading the next step.

---

## 1. Collect stories in scope

Read all stories from:
- All epics under `{pm_state_root}/active/` with `status: in-progress`
- All epics under `{pm_state_root}/planned/` with `status: backlog`

For each epic, list its sprint directories and each sprint's story `.yaml` files (excluding
`sprint.yaml`) to enumerate stories — or use `python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key}` for a quick status roll-up.

For each story, record: `key`, `classification`, `status`, `estimate` (present/absent),
`depends_on`, and whether it is assigned to a sprint.

## 2. Run validation checks

For each story, evaluate the following checks:

| Check | Green | Amber | Red |
|-------|-------|-------|-----|
| Classification | `classification` is `simple`, `standard`, or `complex` | — | Missing or unrecognized value |
| Technical ACs | If `{work_type}` is CODE or MIXED: story file exists with non-empty "Acceptance Criteria" section containing technical details (interfaces, data model, error handling) | Story has only functional ACs (no technical details) | No AC section at all |
| Estimate block | `estimate` block present with at least `man_hours` or `man_hours_low` | — | Estimate block absent |
| `depends_on` validity | All referenced keys exist in scope and are not `done` | — | Any key missing from any state file, or a cycle detected |
| Sprint assignment | Story is assigned to a named sprint in its epic | — | Orphaned story (not in any sprint) |

Technical ACs check only applies when `{work_type}` is CODE or MIXED. For DOCS and CONFIG, skip this check for all stories.

## 3. BMad readiness integration

If `.claude/commands/bmad-check-implementation-readiness.md` or `~/.claude/commands/bmad-check-implementation-readiness.md` exists:

For each CODE or MIXED story, invoke `bmad-check-implementation-readiness` with the story file path. Fold its "not ready" findings into the gate:
- Fewer than half the stories flagged as not ready → amber
- Half or more flagged → red

## 4. Compute gate result

- Any Red finding on any story → `{readiness}` = `red`
- Any Amber finding, no Red → `{readiness}` = `amber`
- All Green → `{readiness}` = `green`

## 5. Write readiness-report.md

Write `{planning_artifacts}/readiness-report.md`:

```markdown
# Readiness Report

Generated: {timestamp}
Gate result: {readiness}
Stories checked: {total_story_count}

## Findings

| Story | Check | Result | Detail |
|-------|-------|--------|--------|
| E001-S01-001 | Technical ACs | 🟡 Amber | Functional ACs only — no interface specs |
| E002-S01-003 | Estimate | 🔴 Red | Missing estimate block |
| E001-S02-001 | depends_on | 🟢 Green | — |

## Summary

- Green: {count}
- Amber: {count}
- Red: {count}
```

## 6. Apply gate outcome

**`{readiness}` = red:**
```
🔴 Readiness check FAILED — {count} blocking issue(s) found.
See {planning_artifacts}/readiness-report.md for details.
Resolve all Red findings before running /l3io-pm-plan again.
```
BLOCKED: readiness gate — red. Do not load the next step.

**`{readiness}` = amber:**
```
🟡 Readiness check passed with warnings — {count} non-blocking issue(s).
Estimates for affected stories will be marked low-confidence.
See {planning_artifacts}/readiness-report.md for details.
Continuing with plan...
```

**`{readiness}` = green:**
```
✅ Readiness check passed — all {count} stories ready.
```

## 7. Output status line

```
Step 02 complete — readiness: {readiness}, stories: {total_story_count}, gaps: {amber_count} amber / {red_count} red
```
