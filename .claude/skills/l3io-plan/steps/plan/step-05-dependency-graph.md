# Step 05: Dependency Graph

Communicate all responses in `{communication_language}`.

Builds the execution dependency graph from `{epic_index}`. Detects cycles,
validates all referenced keys, and produces a topologically sorted phase plan.

---

## 1. Validate depends_on references

For each epic in `{epic_index}`:
- For each key in `depends_on`:
  - If the key is in `{epic_index}` (active or backlog) — valid forward dependency.
  - If the key is in `{archived_epic_keys}` and that epic has `status: done` — valid (already complete).
  - If the key is in `{archived_epic_keys}` but status is not done — flag as **error**: dependency on a non-done archived epic.
  - If the key is not found anywhere — flag as **error**: unknown epic key.
  - If the key equals the epic's own key — flag as **error**: self-dependency.

Story-level `depends_on`:
- Each key must exist in `{story_index}`.
- Unknown story keys → flag as error.

## 2. Detect cycles (epic level)

Run a depth-first cycle detection over the epic dependency edges:

For each epic E with `depends_on: [A, B, ...]`:
- Traverse the dependency chain recursively.
- If E is encountered again during traversal → cycle detected.

Report all cycles found:
```
🔴 Dependency cycle detected: E001 → E003 → E001
```

If any cycle or invalid reference is found, set `{cycle_detected}` = true and halt:
```
BLOCKED: dependency graph has errors — resolve before continuing.
```

## 3. Topological sort → phases

If no errors, group epics into parallel phases using Kahn's algorithm:

1. Start with all epics that have no `depends_on` (or all dependencies done/archived). → **Phase 1**
2. Remove those epics from the pending set. Any epic whose all dependencies are now in completed phases is eligible for the next phase. → **Phase 2**
3. Repeat until all backlog epics are assigned.

**Parallel within a phase:** Epics in the same phase have no dependencies on each other and can run concurrently.

**Example output:**
```
Phase 1 (parallel): E001, E002
Phase 2 (parallel): E003           ← depends on E001 + E002
Phase 3 (sequential): E004         ← depends on E003 only
```

Record as `{phases}`:
```
phases:
  - phase: 1
    parallel: true
    epics: ["E001", "E002"]
    dependencies: []
  - phase: 2
    parallel: true
    epics: ["E003"]
    dependencies: ["E001", "E002"]
  - phase: 3
    parallel: false
    epics: ["E004"]
    dependencies: ["E003"]
```

`parallel` is true if the phase has more than one epic, or if a single-epic phase has no ordering constraint (always true for Phase 1 with one epic).

## 4. Identify critical path

The critical path is the sequence of phases with the highest cumulative wall-clock estimate. If estimates are present on epics, compute:

```
critical_path_phases = phases with the largest Σ estimate.elapsed_hours_high
```

Record as `{critical_path_epics}` = the epics on the critical path in order.

If no estimates are present, `{critical_path_epics}` = all epics in phase order (no differentiation).

## 5. Report graph

```
Dependency graph:

Phase 1 (parallel — {count} epics):
  • E001 "Auth Layer" — no dependencies
  • E002 "API Gateway" — no dependencies

Phase 2 (parallel — {count} epics):
  • E003 "Mobile App" — depends on: E001 ✅, E002 ✅

Critical path: E001 → E003  ({estimated_hours_low}–{estimated_hours_high} hrs)
```

## 6. Output status line

```
Step 05 complete — phases: {phase_count}, epics in graph: {in_scope_epic_count}, critical path: {critical_path_epics joined by " → "}
```
