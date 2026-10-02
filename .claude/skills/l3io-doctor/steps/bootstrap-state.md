## Bootstrap State Mode

Invoked with `bootstrap-state`. Creates state nodes for a project that has story
artifacts but no state tree — typically a project adopting l3io-pm after writing stories
by hand.

**This mode used to write nodes itself**, through an inline `write_node()` calling
`ruamel` directly and assembling state paths at six sites. That bypassed the epic write
lock, the event log and status validation, and nothing tested it. It now runs the same
engine every other migration runs; `scripts/read-artifacts.py` is the reader that serves
it and `scripts/tests/test-read-artifacts.py` covers it.

### Step BS1 — Resolve config

Resolve `{implementation_artifacts}` and `{project-root}` as every other mode does
(`references/config-resolution.md`). Bind:

- `{pm_state_root}` = `{implementation_artifacts}/state`
- `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py`
- `{engine}` = `{skill-root}/scripts/migrate-engine.py`

### Step BS2 — Show what would be created

```bash
uv run {engine} --artifacts {implementation_artifacts} --project-root {project-root} \
  --state-root {pm_state_root} --plan
```

Read-only. Passing `--state-root` in `--plan` mode is what makes the plan **additive**:
any story whose key already has a state node is skipped, and inferred sprint/epic
records are only listed when the state tree does not already carry them. So a project
with partial sharded state — some stories tracked, others newly written by hand — sees a
plan that names only the genuinely new work.

If the detected layout is not `artifacts`, this project already has a legacy status file
— stop and tell the user to run `migrate-state` instead, which handles that source.

If it reports `No migratable source layout found`, there are no story files under
`{implementation_artifacts}/epic-XX/sprint-YY/stories/`. Say so and stop.

If the plan lists zero records but story files exist, every story already has a state
node — nothing to bootstrap. Say so and stop.

### Step BS3 — Explain the inference

The plan reports how many nodes would be `origin: inferred`. Tell the user what that
means, because it is the one thing here they might want to change:

> Your story files carry their own status. Sprints and epics do not exist in this project
> yet, so they are reconstructed from the directory structure your stories sit in, and each
> reconstructed node is marked `origin: inferred` with a note saying so. A sprint is `done`
> when every story in it is done, `backlog` when none has started, and `in-progress`
> otherwise. The same rule gives each epic its status.

If the user wants different sprint boundaries, they change the directory structure and
re-run — the reader follows the tree, so the tree is the control.

### Step BS4 — Confirm

Ask: "Create these state nodes? Existing nodes will be left exactly as they are."

If no: print `Bootstrap cancelled — no changes made.` and stop.

### Step BS5 — Apply

```bash
uv run {engine} --artifacts {implementation_artifacts} --project-root {project-root} \
  --apply --state-root {pm_state_root} --pm-status {pm_status}
```

No `--dispose`: there is no source to retire. The story `.md` files stay exactly where
they are — they are artifacts, and artifacts are never moved.

Every node is written through `{pm_status} import-node`, so each lands under the epic
write lock with an event recorded and its status validated. A node that already exists is
skipped, never overwritten, so re-running after a partial run is safe.

### Step BS6 — Report

**Exit 0:**

```
DONE — created {n} state node(s) under {pm_state_root}.
  {i} node(s) marked origin: inferred.
  Run `/l3io-doctor stats` to see the result.
```

**Exit 1 with `BLOCKED:`** — relay the engine's message verbatim. Nothing was written.

**Exit 1 with `FAILED`** — relay the errors. Nodes already written are valid, and
re-running is safe.

### Step BS7 — What bootstrap does not fill in

Epics created this way carry an empty `title` and `goal`, because nothing in a story
artifact states them. Tell the user they can set them directly:

```bash
uv run {pm_status} set-field --state-root {pm_state_root} --epic {epic_key} \
  --field title --value "{the epic's title}"
```

Estimates and actuals are **not** created. A bootstrapped node has no `estimate` block,
and that is correct: an estimate nobody made is a number calibration would learn from.

---
