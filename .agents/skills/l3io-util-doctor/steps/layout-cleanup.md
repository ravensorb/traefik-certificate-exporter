## Target Folder Structure

There are two mirrored trees under `{implementation_artifacts}/` — `state/` (machine-written
status/estimate/actual data, see `references/status-files.md` for the full schema) and the
top-level `epic-{nnn}/` directories (human/agent-authored artifacts, the ones this skill
reorganizes). They share an identical path suffix — `epic-{nnn}/sprint-{nn}/...` — which is
what lets Health Check 11 diff the two sides directly.

```
{implementation_artifacts}/
├── state/                                   ← machine-written, pm-status.py only — reference only
│   ├── planned/epic-{nnn}/epic.yaml, sprint-{nn}/sprint.yaml, sprint-{nn}/{story-key}.yaml
│   ├── active/epic-{nnn}/...                 (same shape as planned/, one dir per active epic)
│   ├── archived/epic-{nnn}/...               (same shape as planned/, one dir per archived epic)
│   ├── issues.yaml
│   └── pm-calibration.yaml
│
└── epic-{nnn}/                               ← human/agent-authored artifacts (this skill's domain,
    │                                            one such directory per epic)
    ├── sprint-{nn}/
    │   ├── stories/{story-key}.md
    │   ├── closure/...
    │   └── tests/...
    ├── tests/...
    └── epic-closure/...
```

```
{planning_artifacts}/epic-{nnn}/...
{planning_artifacts}/epic-{nnn}/sprint-{nn}/...
```

`nnn` is a zero-padded three-digit epic number (`001`, `002`) and `nn` a zero-padded two-digit
sprint number (`01`, `02`), matching the epic key `E{nnn}` and sprint key `S{nn}`.

This skill never writes under `state/` — that tree is owned exclusively by `pm-status.py`.
It is shown here only so the mirror (and Health Check 11's drift comparison) is clear.

## File Classification Heuristics

1. **Story files** (flat implementation root): regex `^([0-9]+)-[0-9]+.*\.md$` — epic from first capture group; default sprint = `01` unless user provides mapping. Move to: `epic-{nnn}/sprint-{nn}/stories/{story-key}.md`
2. **Sprint closure files** (flat implementation root): patterns `epic-*-sprint-*-retro-*.md`, `*-sprint-*-adversarial-*.md`, `*-sprint-*-redteam-*.md`, `*-sprint-*-clean-release-*.md`, `*-sprint-*-ux-review-*.md`, `*-sprint-*-arch-drift-*.md`. Move to: `epic-{nnn}/sprint-{nn}/closure/{filename}`
3. **Epic closure files** (flat implementation root): patterns `epic-*-adversarial-*.md` (epic-scoped), `epic-*-redteam-*.md`, `epic-*-arch-drift-*.md`, `epic-*-functional-completeness-*.md`, `epic-*-clean-release-*.md`, `epic-*-ux-review-*.md`. Move to: `epic-{nnn}/epic-closure/{filename}`
4. **Test evidence files** (flat roots): patterns `*qa*.md`, `*test*.md`, `*verification*.md`. Sprint-scoped → `epic-{nnn}/sprint-{nn}/tests/`. Epic-scoped → `epic-{nnn}/tests/`.
5. **Planning artifacts** (misplaced under `{planning_artifacts}` or `{implementation_artifacts}`): covers brainstorming, architecture, research, UX specs, and requirements docs — never story or epic tracking files (those are implementation artifacts). Classify by filename pattern:
   - **Architecture**: `*architecture*`, `*arch-spec*`, `*system-design*`, `*tech-design*`
   - **Requirements / PRD**: `*requirements*`, `*prd*`, `*brief*`, `*spec*` (excluding story files matched by heuristic 1)
   - **UX spec**: `*ux-spec*`, `*ux-design*`, `*wireframe*`, `*mockup*`, `*ui-spec*`
   - **Research / spike**: `*research*`, `*spike*`, `*investigation*`, `*discovery*`
   - **Brainstorming**: `*brainstorm*`, `*ideation*`, `*mind-map*`
   Determine placement scope from the filename: if `sprint-{nn}` or `sprintSS` is present → `{planning_artifacts}/epic-{nnn}/sprint-{nn}/{filename}`; otherwise → `{planning_artifacts}/epic-{nnn}/{filename}`. If epic cannot be inferred from the filename, ask for a mapping before proceeding.
6. **Unknown files**: leave in place; record as "unclassified".

## Execution Sequence

### Step 1 — Scan and Classify

Recursively scan **all files** under `{implementation_artifacts}` and `{planning_artifacts}` — including any subdirectories at any depth (flat roots, unusual subfolders, nested paths). Do not limit the scan to top-level files.

For each file found, determine whether it is already correctly placed:
- A file is **correctly placed** if its current path exactly matches the target path the heuristics would produce. Skip it — record as `already-placed`.
- A file is **misplaced** if it is classifiable but lives outside its correct target location (flat root, wrong epic/sprint folder, unusual subfolder, etc.). Add it to the move map.
- A file is **unclassified** if no heuristic can determine its destination. Leave in place and record.

Apply classification heuristics to all misplaced files. Build move map: source path → destination path + classification.

For files where epic/sprint cannot be reliably determined from filename alone, ask for a mapping before proceeding to Step 2.

### Step 2 — Dry-Run Table

Print the full move plan:

```
DRY RUN — Artifact Cleanup
===========================================================
Source                          → Destination                         Class            Status
-----------------------------------------------------------
{source-path}                   → {dest-path}                        story            move
{source-path}                   → {dest-path}                        sprint-closure   move
{source-path}                   → {dest-path}                        story            conflict (dest exists)
{source-path}                   → (already correct)                  story            already-placed
{source-path}                   → (no destination found)             —                unclassified
===========================================================
Summary: {move-count} to move, {already-placed-count} already correct, {conflict-count} conflicts, {unclassified-count} unclassified
```

### Step 3 — Confirmation

Ask: "Proceed with {move-count} file moves? Conflicts and unclassified files will not be touched."

If no: print "Cleanup cancelled — no files changed." and exit.

### Step 4 — Create Directories

Create all required destination directories that do not exist yet.

### Step 5 — Execute Moves

Move each confirmed file to its destination. On conflict (destination already exists): skip, record. Log each move.

### Step 6 — Reference Reconciliation

Search reference-holding files: the split status files (`sprint-status.yaml`, `sprint-status-backlog.yaml`, `sprint-status-archived.yaml`) or legacy `sprint-status.yaml.legacy` (whichever are present), story `.md` files, planning docs, closure and test reports. For each moved file, replace exact old-path occurrences with the new path. If one old path could match multiple targets or context is ambiguous, record for manual review — do not auto-update.

### Step 7 — State Verification

Verify post-move state:
- Epic and sprint folder names are zero-padded (`epic-001` not `epic-01` or `epic-1`, `sprint-02` not `sprint-2`)
- Story files under `stories/`, closure outputs under `closure/`, tests under `tests/`
- Check story state entries in whichever status files are present (split layout or legacy `sprint-status.yaml`) for references to missing story files
- Flag any residual flat files that were not classified and remain in the root

**Ordering check (status files):** If the split layout exists (`sprint-status.yaml`, `sprint-status-backlog.yaml`, or `sprint-status-archived.yaml`), check their sort order:
- Epics ordered ascending by `id` (numeric) in each file
- Sprints ordered ascending by `id` (numeric) within each epic
- Stories ordered ascending by `key` (lexicographic) within each sprint
- Backlog items in `sprint-status-backlog.yaml` ordered by `epic` ascending (numeric; blank entries last), then `sprint`, then `key`

If any ordering issue is found, include it in the State Issues count and append to the summary:
```
Status file ordering: {N} issue(s) detected in {files} — no automated fix; this split-file
  layout predates the sharded state/ convention, where ordering can't drift. Reorder the
  list(s) manually, or run `migrate-state` to move to the sharded layout.
```
If all files are in order, append:
```
Status file ordering: ✓ all files sorted correctly
```

### Step 8 — Deferred Work Files

For each epic that has conflicts, unclassified files, or manual-review reference items, write a consolidated deferred work file:

```
{implementation_artifacts}/epic-{nnn}/cleanup-deferred.md
```

Format:
```markdown
# Cleanup Deferred Work — Epic {nnn}
Generated: {date}

## Conflicts (destination already exists — not moved)
- `{source-path}` → `{dest-path}` [{classification}]

## Unclassified Files (no heuristic match — left in place)
- `{source-path}`

## Reference Updates Requiring Manual Review
- File: `{reference-file}` — old path `{old-path}` matched multiple targets or context was ambiguous
```

Omit any section that has no entries. If an epic has no deferred items, do not write the file.

If a `cleanup-deferred.md` already exists for an epic (from a prior run), append new findings under a dated `## Run {date}` heading rather than overwriting.

### Step 9 — Summary Report

Print:
```
DONE - Moved: N, Conflicts: N, Unclassified: N, Refs Updated: N, Ref Conflicts: N, State Issues: N
  Implementation root: {implementation_artifacts}
  Planning root:       {planning_artifacts}
  Deferred work files: {deferred_file_list} (or "none")
```

### Step 10 — Completeness Verification Loop

Maintain `{cleanup_iteration}` = 1 (incremented each time Step 1–8 runs).

After Step 8, recursively re-scan all files under `{implementation_artifacts}` and `{planning_artifacts}` (same full-depth scan as Step 1) for any remaining misplaced classifiable files — excluding known conflicts, already-placed files, and intentionally unclassified files recorded in the previous pass.

If no classifiable files remain: print `Cleanup complete — no residual files found after {cleanup_iteration} pass(es).` and exit.

If classifiable files remain and `{cleanup_iteration}` < 4: announce the residual files found, then automatically loop back to Step 1 with only those files in scope. Increment `{cleanup_iteration}`.

If `{cleanup_iteration}` ≥ 4 and classifiable files still remain, halt:
```
Cleanup HALT — {residual_count} classifiable file(s) remain after {cleanup_iteration} passes.
Residual files: {residual_file_list}
These may require manual mapping or indicate ambiguous filenames the heuristics cannot resolve.
```
Present the residual list and wait for `{user_name}` guidance before exiting.

---
