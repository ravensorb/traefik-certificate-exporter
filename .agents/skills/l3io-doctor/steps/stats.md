## Stats Mode

Invoked with the `stats` argument, or with its aliases `backlog` / `issues`. Read-only
plan-aware progress dashboard — renders the phase → epic → sprint → story hierarchy via
`pm-status.py report`, then appends the backlog, calibration, and last-closed sections that
`report` does not cover. No files are changed.

**One `list-issues` call serves both views.** Step ST2 already reads the whole backlog
(`--all`) to produce the counts, so the per-item table in Step ST4 costs nothing extra; it
used to be a separate `backlog` mode that made the identical call and formatted it. Under the
`backlog`/`issues` alias the per-item table is always printed and the hierarchy uses the
default scope; under `stats` the table is printed whenever there is at least one open item.

### Steps

**Step ST1 — Load config and detect layout**

Load config (same as layout cleanup). Run the same three-way count Check 2b uses (Check 2b in
`steps/health-check.md` is the source of the multi-layout condition and its Critical severity
below — this makes a third copy of layout detection, alongside Check 2b and
`l3io-help/steps/step-02-detect-layout.md`; keep the multi-layout branch in sync with Check 2b's
condition and severity if either changes):

```bash
SHARDED=$([ -d "{pm_state_root}" ] && echo 1 || echo 0)
LEGACY_EPIC=$([ -d "{project-root}/_bmad/state" ] && echo 1 || echo 0)
LEGACY_FLAT=$([ -f "{implementation_artifacts}/sprint-status.yaml" ] && echo 1 || echo 0)
```

Apply the first matching rule:

- **More than one of the three is 1** → an earlier migration did not finish, and the sharded
  tree this dashboard would otherwise walk cannot be trusted as the sole source of truth while
  a legacy layout also exists — the same condition Check 2b flags Critical. A confidently
  rendered tree over ambiguous state is worse than a refusal, so **BLOCK**. Print and exit —
  do not proceed to Step ST2:
  ```
  BLOCKED: multiple state layouts detected (sharded=$SHARDED legacy-per-epic=$LEGACY_EPIC
  legacy-flat=$LEGACY_FLAT). An earlier migration did not finish. Run
  /l3io-doctor migrate-state first, then re-run /l3io-doctor stats.
  ```
- **Sharded present, and it is the only layout present** → walk it (Step ST2). This is the
  normal path.
- **Sharded absent, a legacy layout present** → the dashboard cannot read it. Print and exit:
  ```
  State is still on a legacy layout ({legacy per-epic | legacy flat}) — stats reads the
  sharded state tree at {pm_state_root}. Run /l3io-doctor migrate-state first.
  ```
- **Nothing present** → before concluding there is nothing to report, rule out an orphan
  caused by `implementation_artifacts` having been repointed — an empty probe result here is
  not proof there is no history. Ask the script that owns this decision:
  ```bash
  uv run {skill-root}/scripts/detect-layout.py --artifacts {implementation_artifacts} \
    --project-root {project-root} --reachability --format json
  ```
  It prints every state tree it can find outside `{implementation_artifacts}` and exits 4 when
  there is one. This used to be an inline `git ls-files` + `find` pair carried here and in
  `l3io-help/steps/step-02-detect-layout.md`, with a comment asking the next person to keep
  the two in sync; `scripts/tests/test-detect-layout.py` now covers it instead. **pm-help still
  carries its own copy** — the remaining one.
  If either prints a path that is not under `{implementation_artifacts}/state`, a confidently
  empty dashboard over existing state elsewhere is the same "wrong beats a refusal" failure as
  the multi-layout case above, so **BLOCK**. Print and exit — do not print "nothing to report":
  ```
  BLOCKED: state found at <printed-path> but implementation_artifacts resolves to
  {implementation_artifacts}. Did implementation_artifacts change? Refusing to show an empty
  dashboard over existing state.
  ```
  If both print nothing → genuine first run. Print `No state found at {pm_state_root} —
  nothing to report.` and exit.

**Step ST2 — Compute the hierarchy**

Do not walk the tree by hand. `pm-status.py` is the only component that resolves a node key to
a path, and a second walk here would drift from it the next time the layout changes. Run:

```bash
uv run {project-root}/_bmad/scripts/pm-status.py report \
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
Self-install at activation should have installed it; re-run /l3io-doctor stats, and if
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

- **Backlog items** — `uv run {pm_status} list-issues --state-root {pm_state_root} --all --format json`: count `open` by severity (Critical, High, Medium, Low, unknown) and by status (untriaged = `backlog`, `scheduled`) plus `origin_archived`; count `resolved` by `resolution`. An absent file = zero items, not an error. **Keep the `open` records themselves, not only the counts** — Step ST4 prints them per item from this same call; do not make a second `list-issues` call for it.
- **Last closed sprint** — across all epics, the highest `epic-{nnn}/sprint-{nn}` whose `sprint.yaml` has `status: done` (lexical order over the zero-padded names is the correct order — §8).
- **Last closed epic** — the highest `epic-{nnn}` under `{pm_state_root}/archived/`; note its key and title.
- **Calibration file** — check `{pm_calibration_file}` (`{pm_state_root}/pm-calibration.yaml` — migrate-state moves it here from `{project-root}/_bmad/`); if present, note its version and the number of scope/closure/fix sample entries.

**Step ST3 — Print dashboard**

Print the hierarchy first. Re-run `report` in `tree` form rather than re-rendering the JSON by
hand — hand-rendering it would drift from the tool's own view:

```bash
uv run {project-root}/_bmad/scripts/pm-status.py report \
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
  untriaged: {n}  scheduled: {n}  origin archived: {n}
  resolved: {n}  (fixed {n} · wontfix {n} · duplicate {n} · obsolete {n})
Last sprint closed:  Epic {nnn} / Sprint {nn}  (or "none")
Last epic closed:    E{nnn} — {title}          (or "none")
Calibration file:    {version}, {n} scope samples  (or "not found")
Layout:              Sharded state tree
================================================================
```

Placement anomalies no longer need their own line — they appear in the tree's `Anomalies` block,
alongside stale locks and unreadable node files.

**Three follow-ups on the tree output, only in this branch** (Step ST2 ran the report; the
Step ST2b counts-only fallback below has no tree to check) **and only when the output
warrants them:**

- Always append a live-view pointer, because that is what answers "what is happening right
  now" during a long run:
  ```
  For a live view during a run: uv run {pm_status} report --state-root {pm_state_root} \
    --plan {planning_artifacts}/plan-output-meta.yaml --watch 15
  ```
- If the tree contains `⚠ STALE LOCK`, append this recommendation for each affected epic:
  `Epic {key} has a stale lock (claimed {N}m ago). Run: uv run {pm_status} clear-lock
  --state-root {pm_state_root} --epic {key}`. Do not re-derive stale-lock state yourself — the
  report already computed it from `_lock.ttl_minutes`. (The same remedy also appears in
  `l3io-help/steps/step-05-recommend.md` — a cross-skill duplication. `check:docs`
  check 4 validates each copy against the real CLI, so a renamed subcommand or a flag that
  stops existing fails CI in both; what nothing checks is the two copies saying *different*
  things, so keep them in sync by hand if the remedy changes.)
- If the tree ends with the `~ dwell times are approximate` note, add: `Dwell times sharpen
  once state/events.jsonl accumulates transitions — it starts recording on the next
  /l3io-execute run.`

**Step ST4 — Per-item backlog table**

From the `open` records Step ST2 already read — no second `list-issues` call. Print this when
the argument was `backlog`/`issues`, or when `stats` found at least one open item. Group by
severity (Critical → High → Medium → Low → unknown); within a group sort by `epic` then `key`.
`scheduled` items show the story they are scheduled into; `origin_archived` items are marked.
Each item carries a `kind` — `defect` (the default, and what an absent field means) plus
`spec-change` and `spec-proposal`, which epic closure's spec sync files and `triage`'s spec
pass resolves:

```
----------------------------------------------------------------
BACKLOG — {pm_issues_file}
Sev    Key           Epic  Sprint  Kind        Status              Title
----------------------------------------------------------------
High
  HIGH   BL-E001-002   001   —       defect      scheduled E003-S02-004  {title}
Low
  LOW    BL-E002-001   002   03      spec-change backlog (archived)      {title}
----------------------------------------------------------------
Run /l3io-doctor triage to audit these and close what is already fixed.
```

Truncate titles at 50 characters with `…`. Show the sprint as `—` when blank. With no open
items, print `Backlog is empty — no open items.` in place of the table.

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
