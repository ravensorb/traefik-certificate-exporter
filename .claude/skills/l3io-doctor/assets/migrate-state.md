## Migrate State Mode

Invoked with `migrate-state`. Upgrades any earlier state layout to the current sharded
tree under `{implementation_artifacts}/state/`.

**The parsing and writing are not done here.** `scripts/migrate-engine.py` owns them and
`scripts/tests/test-engine.py` covers them. This file owns what a script cannot: deciding
what to tell the user, taking the confirmation, and interpreting a refusal.

Six hand-written procedures used to live here, none reachable by a test. One deleted a
live BMad tracking file while reporting success, because its completeness checks ran
*after* the write and passed vacuously over an empty set. The engine's gate now sits
before the write, so that cannot happen for this cause or any other.

### Step MS1 — Resolve config

Resolve `{implementation_artifacts}` and `{project-root}` exactly as every other mode does
(`references/config-resolution.md`). Bind:

- `{pm_state_root}` = `{implementation_artifacts}/state`
- `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py`
- `{engine}` = `{skill-root}/scripts/migrate-engine.py`

### Step MS2 — Show the plan

```bash
uv run {engine} --artifacts {implementation_artifacts} --project-root {project-root} --plan
```

Read-only. Prints the detected layout, the node counts, and how many nodes would be
marked `origin: inferred`.

If it prints `No migratable source layout found`, report that and stop. That is a normal
outcome, not a failure.

### Step MS3 — Explain what was detected

Tell the user in one short paragraph which layout was found and what it means. One case
needs more than a sentence:

**If the layout is `bmad-flat`**, say plainly that this project is tracked by base BMad's
own `sprint-status.yaml`; that `bmad-sprint-planning`, `bmad-build` and
`bmad-retrospective` all read it; and that the migration renames it to `.legacy` rather
than deleting it — so those skills will stop finding it. Ask whether to proceed. This is a
real change to how their project is tracked, and it is the one decision here that is not
mechanical.

### Step MS4 — Confirm

Ask: "Proceed with the migration? The source will be renamed to `.legacy`, never deleted."

If no: print `Migration cancelled — no changes made.` and stop.

### Step MS5 — Apply

```bash
uv run {engine} --artifacts {implementation_artifacts} --project-root {project-root} \
  --apply --state-root {pm_state_root} --pm-status {pm_status} --dispose
```

The engine gates, writes every node through `{pm_status} import-node`, verifies the result
against the plan, and only then renames the source aside.

### Step MS6 — Interpret the outcome

**Exit 0** — report the counts it printed and point at `stats`:

```
DONE — migrated {n} node(s) to {pm_state_root}.
  The previous source is preserved as *.legacy.
  Run `/l3io-doctor stats` to see the result.
```

**Exit 1 with `BLOCKED:`** — the gate refused. Nothing was written and the source is
untouched. Relay the engine's message verbatim; do not paraphrase it and do not retry. The
most common cause is named in the message: a flat `sprint-status.yaml` holding BMad's
`development_status:` mapping. Confirm with:

```bash
uv run {skill-root}/scripts/detect-layout.py --artifacts {implementation_artifacts} --classify
```

**Exit 1 with `FAILED`** — the write or the verification failed. Nothing was disposed of
and the source is intact. Relay the errors. The state tree may hold partially written
nodes; they are valid nodes, and re-running is safe because `import-node` skips what
already exists.

### Step MS7 — Calibration and anomalies

If `{project-root}/_bmad/pm-calibration.yaml` exists, move it to
`{pm_state_root}/pm-calibration.yaml` with `git mv`. It is the only file that moves rather
than being rewritten.

Record anything the user should know about as a backlog item:

```bash
uv run {pm_status} append-issue --state-root {pm_state_root} --epic {epic_key} \
  --severity Low --source migrate-state --description "{what was odd}"
```

---
