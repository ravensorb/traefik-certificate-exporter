## Stats Mode

Invoked with `stats` argument. Read-only plan-aware progress dashboard — renders the
phase → epic → sprint → story hierarchy via `pm-status.py report`, then appends the backlog,
calibration, and last-closed sections that `report` does not cover. No files are changed.

### Steps

**Step ST1 — Load config and detect layout**

Load config (same as layout cleanup). Run the same three-way count Check 2b uses:

```bash
SHARDED=$([ -d "{pm_state_root}" ] && echo 1 || echo 0)
LEGACY_EPIC=$([ -d "{project-root}/_bmad/state" ] && echo 1 || echo 0)
LEGACY_FLAT=$([ -f "{implementation_artifacts}/sprint-status.yaml" ] && echo 1 || echo 0)
```

- **Sharded present** → walk it (Step ST2). This is the normal path.
- **Sharded absent, a legacy layout present** → the dashboard cannot read it. Print and exit:
  ```
  State is still on a legacy layout ({legacy per-epic | legacy flat}) — stats reads the
  sharded state tree at {pm_state_root}. Run /l3io-util-doctor migrate-state first.
  ```
- **Nothing present** → print `No state found at {pm_state_root} — nothing to report.` and exit.

**Step ST2 — Compute the hierarchy**

Do not walk the tree by hand. `pm-status.py` is the only component that resolves a node key to
a path, and a second walk here would drift from it the next time the layout changes. Run:

```bash
python3 {project-root}/_bmad/scripts/pm-status.py report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format json
```

This is read-only: `report` writes only when `--out` is passed, and it is not passed here.

From the JSON take `totals` (epics/sprints/stories by status), `phases` (`phase`, `epic_done`,
`epic_total`), and `flags` — `placement` entries are the placement anomalies this mode already
reported, while `stuck` and `stale-lock` are new and worth surfacing here too.

This skill self-installs `{pm_status}` at activation, before any mode file is loaded, so it
should already be present here. If `{project-root}/_bmad/scripts/pm-status.py` still does not
exist, self-install itself failed — print this and use Step ST2b:

```
pm-status.py is not installed — showing counts only, without the plan-aware hierarchy.
Self-install at activation should have installed it; re-run /l3io-util-doctor stats, and if
this persists, check that {project-root}/_bmad/scripts/ is writable.
```

`report` does not cover the backlog, the calibration file, or the last-closed markers. Read
those directly as listed below; they remain part of this dashboard.

**Step ST2b — Counts-only fallback**

Only when `pm-status.py` is absent. The tree is one bare-node YAML file per node; the directory
structure *is* the child list (`references/status-files.md` §4). Enumerate:

```bash
ls -d {pm_state_root}/{planned,active,archived}/epic-*/ 2>/dev/null
```

For each epic directory: read `epic.yaml`; for each `sprint-{nn}/` inside it read
`sprint.yaml`; for each `*.yaml` in that sprint directory other than `sprint.yaml` read the
story node. Accumulate:

- **Epics** by `status` (backlog, in-progress, done) — count per status, total. The status
  folder and the node's `status` agree by construction (`planned`→backlog, `active`→in-progress,
  `archived`→done); if any epic disagrees with its folder, note it as a placement anomaly.
- **Sprints** by `status` (backlog, in-progress, done) — count per status, total.
- **Stories** by `status` (backlog, ready-for-dev, in-progress, review, done) — count per status, total.

**Read directly in both branches:**

- **Backlog items** — the `backlog:` list in `{pm_issues_file}` — count by severity (Critical, High, Medium, Low, unknown), total. Absent file = zero items, not an error.
- **Last closed sprint** — across all epics, the highest `epic-{nnn}/sprint-{nn}` whose `sprint.yaml` has `status: done` (lexical order over the zero-padded names is the correct order — §8).
- **Last closed epic** — the highest `epic-{nnn}` under `{pm_state_root}/archived/`; note its key and title.
- **Calibration file** — check `{pm_calibration_file}` (`{pm_state_root}/pm-calibration.yaml` — migrate-state moves it here from `{project-root}/_bmad/`); if present, note its version and the number of scope/closure/fix sample entries.

**Step ST3 — Print dashboard**

Print the hierarchy first. Re-run `report` in `tree` form rather than re-rendering the JSON by
hand — hand-rendering it would drift from the tool's own view:

```bash
python3 {project-root}/_bmad/scripts/pm-status.py report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format tree
```

**Scope — map what the user asked for to a `--status` filter.** The state tree's three
folders are the vocabulary: `planned` = backlog, `active` = in progress, `archived` = done.

| They asked for | Pass |
|---|---|
| nothing, "progress", "status" | *(nothing — defaults to planned + active)* |
| "what's active", "in flight", "what's running", "in progress", "what's moving" | `--status active` |
| "what's queued", "backlog", "not started", "what's next" | `--status planned` |
| "everything", "including done", "including archived", "all" | `--all` |

Counting is unaffected by the filter: totals and phase denominators always cover every epic,
so a narrowed view never changes what "2/3 epics done" means. When the filter is not the
default the report prints a `SHOWING …` banner itself — do not add your own caveat.

Print the output verbatim, then append the sections `report`
does not cover:

```
----------------------------------------------------------------
Backlog items
  Critical: {n}  High: {n}  Medium: {n}  Low: {n}  total: {n}
Last sprint closed:  Epic {nnn} / Sprint {nn}  (or "none")
Last epic closed:    E{nnn} — {title}          (or "none")
Calibration file:    {version}, {n} scope samples  (or "not found")
Layout:              Sharded state tree
================================================================
```

Placement anomalies no longer need their own line — they appear in the tree's `Anomalies` block,
alongside stale locks and unreadable node files.

**When Step ST2b ran** (no `pm-status.py`), print the flat form instead, followed by the same
appended block above:

```
PROJECT STATE — {pm_state_root}
================================================================
Epics
  in-progress:  {n}    backlog: {n}    done: {n}    total: {n}
Sprints
  in-progress:  {n}    backlog: {n}    done: {n}    total: {n}
Stories
  done:         {n}    in-progress: {n}    review: {n}
  ready-for-dev:{n}    backlog: {n}         total: {n}
Placement anomalies: none  (or list epics whose status disagrees with their folder)
```

---
