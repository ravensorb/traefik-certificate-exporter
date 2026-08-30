# Migrate State: Legacy Layouts → Sharded State Tree

Communicate all responses in `{communication_language}`.

Migrates l3io-pm state from either the legacy flat `sprint-status*.yaml` layout or the
legacy per-epic `{project-root}/_bmad/state/` layout to the sharded layout —
`{implementation_artifacts}/state/{planned,active,archived}/epic-{nnn}/[sprint-{nn}/]`,
one bare-node YAML file per epic/sprint/story — described in the PM skills' canonical
`references/status-files.md` (source: `skills/_shared/status-files.md`; this skill does not
ship its own copy, but the layout it defines is the migration target here).

**This procedure moves the project's real state.** Stages A–E are entirely non-destructive
— they only read the legacy sources and write the new sharded tree; nothing is removed.
**Stage F is the only stage that deletes anything, and it only runs after Stage E has
verified the migration in full.** Read Stage F before confirming anything there. Nothing in
this procedure overwrites an existing file — every write target is either brand-new or
gated by an existence check.

## Bindings

Resolve config per `{skill-root}/references/config-resolution.md`:

```bash
uv run --python 3.11 {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}
```

Bind from `modules.l3io-pm`, falling back to the documented defaults:

- `{implementation_artifacts}`
- `{planning_artifacts}`

Then bind:
- `{pm_state_root}` = `{implementation_artifacts}/state`
- `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py`
- `{pm_issues_file}` = `{pm_state_root}/issues.yaml`
- `{pm_calibration_file}` = `{pm_state_root}/pm-calibration.yaml`

This skill self-installs `{pm_status}` at activation (`SKILL.md` `## On Activation`), before
any mode file — including this one — is loaded, so it should already be present and current
by the time this stage runs. If it is still missing on disk, self-install itself failed —
BLOCK:
```
BLOCKED: {pm_status} not found. Self-install at activation did not complete — check that
{project-root}/_bmad/scripts/ exists and is writable, then re-run /l3io-util-doctor migrate-state.
```

If it does exist, it can in principle still be a stale copy — self-install above should
already rule this out, but check its version marker before proceeding as a defensive
measure rather than trusting that guarantee blindly. Stage E below calls `verify
--state-root`, a flag older copies of `pm-status.py` do not accept, so catch a stale copy
now with an actionable message rather than letting Stage E fail on an opaque argparse error:

```bash
REQUIRED="2.2.0"
FOUND=$(grep -m1 "pm-status-version:" "{pm_status}" 2>/dev/null | sed 's/.*pm-status-version://' | awk '{print $1}')
echo "required=$REQUIRED found=${FOUND:-none}"
```
If `$FOUND` is empty (marker absent or file unreadable) or lower than `$REQUIRED` —
`[ -z "$FOUND" ] || [ "$(printf '%s\n%s\n' "$REQUIRED" "$FOUND" | sort -V | head -1)" != "$REQUIRED" ]`
— BLOCK (never treat a missing or malformed marker as "new enough"):
```
BLOCKED: {pm_status} is version {found}, but this migration requires {required} or newer.
Self-install at activation should have refreshed it — re-run /l3io-util-doctor migrate-state;
if this persists, check that {project-root}/_bmad/scripts/ is writable.
```

## Pre-flight

Detect which layout(s) are present, using the identical three-way count
`step-00-activate.md` uses (do not stop at the first match — count all three):

```bash
SHARDED=$([ -d "{implementation_artifacts}/state" ] && echo 1 || echo 0)
LEGACY_EPIC=$([ -d "{project-root}/_bmad/state" ] && echo 1 || echo 0)
LEGACY_FLAT=$([ -f "{implementation_artifacts}/sprint-status.yaml" ] && echo 1 || echo 0)
echo "sharded=$SHARDED legacy-per-epic=$LEGACY_EPIC legacy-flat=$LEGACY_FLAT"
```

**If `SHARDED=1`** → a sharded tree already exists at `{pm_state_root}`. BLOCK
unconditionally, regardless of what else is present — this command never writes into or
over an existing sharded tree. Name **everything** found, not just the sharded tree, so the
user knows the full picture:
```
BLOCKED: {pm_state_root} already exists. migrate-state never overwrites an existing
sharded tree. If an earlier migration was interrupted, inspect {pm_state_root} by hand —
do not re-run this command over it. If it is already complete and correct, there is
nothing left to do here.
```
Then, if `LEGACY_EPIC=1`, append:
```
Also found: a legacy per-epic layout still present at {project-root}/_bmad/state/. This is
very likely the leftover source of an interrupted migration and needs manual cleanup once
the sharded tree above is confirmed correct — do not delete it until then.
```
And, if `LEGACY_FLAT=1`, append:
```
Also found: a legacy flat layout still present at {implementation_artifacts}/sprint-status*.yaml.
Same as above — needs manual cleanup once the sharded tree is confirmed correct, not before.
```

**Else if `LEGACY_EPIC=1` and `LEGACY_FLAT=1`** → both legacy layouts present at once.
This means an earlier migration did not finish, or the project's state is genuinely
ambiguous. BLOCK:
```
BLOCKED: both the legacy per-epic layout (_bmad/state/) and the legacy flat layout
(sprint-status.yaml) are present. An earlier migration did not finish. Do not guess which
is authoritative — inspect both locations by hand, remove or rename the stale one, then
re-run migrate-state.
```

**Else if `LEGACY_EPIC=1`** → legacy per-epic source. Bind `{source_layout}` =
`legacy-per-epic`. Skip Stage A (it reads the legacy *flat* files) and continue to
"Loading the working lists" below. Everything after that point — status normalization,
cross-reference normalization, Stage B onward — runs for **both** source layouts.

**Else if `LEGACY_FLAT=1`** → legacy flat source. Bind `{source_layout}` = `legacy-flat`.
Continue to Stage A.

**Else (`LEGACY_FLAT=0`, `LEGACY_EPIC=0`, `SHARDED=0`)** → nothing to migrate:
```
Nothing to migrate — no legacy flat, legacy per-epic, or sharded state found under
{implementation_artifacts} or {project-root}/_bmad/state/. If this is a new project,
state will be created lazily on first use of any l3io-pm skill.
```
Exit. This is not an error.

---

## Stage A — legacy flat load and key conversion (legacy flat source only; skip entirely when `{source_layout} = legacy-per-epic`)

Read whichever of these three files exist (missing files are treated as empty —
`{epics: [], backlog: []}`; do **not** require all three):

```bash
ls {implementation_artifacts}/sprint-status.yaml \
   {implementation_artifacts}/sprint-status-backlog.yaml \
   {implementation_artifacts}/sprint-status-archived.yaml 2>/dev/null
```

Load all `epics:` lists found across whichever files are present into one in-memory
**working epic list** — a node's current `status` decides its fate below, not which file
it happened to be found in (this matches how the original migrate-state.md always treated
the three files as one logical set). Load any top-level `backlog:` list found (normally
only present in `sprint-status-backlog.yaml`) into an in-memory **working issues list**.
**Do not write any output yet** — Stage A is entirely in-memory; Stage C performs the
actual writes.

Status normalization is **not** done here — it is a shared step that runs for both source
layouts, after this stage and after the legacy-per-epic load below. See "Status
normalization — every node lands on a status the sharded layout accepts".

### Node key conversion — necessary for the sharded layout, not present in the previous version of this file

Legacy flat epic and sprint nodes use `id:` (a bare integer, e.g. `id: 3`). The sharded
layout requires `key:` on every node (the PM skills' `references/status-files.md` §3),
zero-padded — `'E{nnn}'` (3-digit) for epics, `'S{nn}'` (2-digit) for sprints. Convert, for
every epic and sprint node in the working epic list (regardless of what the status
normalization step will later do to it):

- Epic: `id: 3` → `key: 'E003'`. Drop the old `id:` field.
- Sprint: `id: 1` → `key: 'S01'`. Drop the old `id:` field.

Story nodes already carry `key:` in the legacy flat layout (format `E{nnn}-S{nn}-{nnn}`)
and need no conversion here — only the `epic:`/`sprint:` back-references added in Stage B.

For backlog items extracted by the status-normalization step below, no key is built by
hand — Stage C passes the epic's numeric id straight to `append-issue --epic`, which
normalizes it to the same 3-digit width as the epic's freshly-converted `key:` (e.g. epic
`id: 3` → `key: 'E003'` → issue key `BL-E003-{nnn}`, never `BL-E3-` or `BL-E03-`) and
allocates `{nnn}` itself. Pre-existing
backlog items already in the working issues list are **left exactly as found** — their
keys are not reformatted (see Stage C; re-keying an item that may already be referenced
elsewhere, e.g. by `l3io-pm-sync`, is out of scope and a needless risk for this
migration).

At the end of Stage A, the working epic list is in the same shape a legacy per-epic source
would be: `key:`-addressed epics, each with a full nested `sprints:` list, each sprint
with a full nested `stories:` list. This is the shared input Stage B consumes for both
source layouts.

---

## Loading the working lists (legacy per-epic source only; skip when `{source_layout} = legacy-flat` — Stage A already built them)

Read every source file:

```bash
ls {project-root}/_bmad/state/active/E*-status.yaml 2>/dev/null
cat {project-root}/_bmad/state/sprint-status-planned.yaml 2>/dev/null
cat {project-root}/_bmad/state/sprint-status-archived.yaml 2>/dev/null
```

Concatenate the `epics:` list from every `active/E{nnn}-status.yaml` file, from
`sprint-status-planned.yaml`, and from `sprint-status-archived.yaml` into one **working
epic list**. No `id:`→`key:` conversion is needed — legacy per-epic nodes already use
`key:`. Their **statuses**, however, are *not* guaranteed to be current: `deferred` and
`superseded` are documented legacy statuses that a per-epic tree can carry, so the status
normalization step below runs on this path too.

Load `{project-root}/_bmad/state/sprint-status-issues.yaml`'s `backlog:` list as the
**working issues list**, unchanged.

---

## Status normalization — every node lands on a status the sharded layout accepts (both source paths)

**Run this for both source layouts.** It is the only thing standing between a legacy
status and a node the rest of the toolchain cannot write to.

`pm-status.py` accepts exactly these values, and rejects everything else with exit 2:

| Node type | Accepted statuses (`pm-status.py`) |
|---|---|
| Epic | `backlog`, `in-progress`, `done` (`VALID_EPIC_STATUS`) |
| Sprint | `backlog`, `in-progress`, `done` (`VALID_SPRINT_STATUS`) |
| Story | `backlog`, `ready-for-dev`, `in-progress`, `review`, `done` (`VALID_STORY_STATUS`) |

A node that reaches the sharded tree still carrying `deferred` is not merely untidy: Stage B
would have nowhere to put it, and every later `set-status` on it exits 2. Normalize before
Stage B decides placement.

Apply to every epic, sprint, and story node in the working epic list. These are the same
rules this file has always used for legacy flat cleanup — they are not being reinvented,
only promoted to cover both source paths. The table is idempotent on a node whose status is
already accepted, so running it on a legacy-per-epic source costs nothing and closes the gap:

| Node type | Legacy status | Condition | Normalized to |
|-----------|--------------|-----------|---------------|
| Epic | `deferred` | no sprint has `status: done` | `backlog` |
| Epic | `deferred` | ≥1 sprint has `status: done` | `in-progress` |
| Epic | `superseded` | any | `done` (preserve the `superseded_by` field unchanged) |
| Sprint | `deferred` | — | `backlog` |
| Sprint | `superseded` | — | `done` |
| Story | `deferred` | — | extracted as a backlog issue; **removed** from the sprint's story list |
| Story | `superseded` | — | `done` |
| Any | already an accepted value (table above) | — | unchanged |

**Any other status → halt.** Never improvise a destination folder, never leave the value as
found, and never write a partial tree. Nothing has been written to `{pm_state_root}` at this
point, so stopping here is clean:

```
BLOCKED: unrecognized {epic|sprint|story} status '{status}' on node {key}. migrate-state
has no destination for it and will not guess — guessing would either put the node in the
wrong status folder or leave a status that makes every later pm-status.py write on that
node fail with exit 2. Nothing has been written; {pm_state_root} was not created.
Set that node's status in the source file to one of the accepted values for its type
(epic/sprint: backlog | in-progress | done; story: backlog | ready-for-dev | in-progress |
review | done), or to a legacy status this migration knows how to normalize (deferred,
superseded), then re-run migrate-state.
```

For deferred stories extracted as backlog issues: record `severity: Low`, `source:
migrate-state (deferred)`, and the story's title for each — but **do not assign a key
here**. The `BL-E{epic}-{nnn}` key is allocated later, in Stage C, by `append-issue` itself
under a lock, from the highest existing suffix for that epic; computing it by hand at this
step would be the same invented-number collision this migration's own writer was changed
to close off. This step's job is only to identify *which* stories are being extracted and
capture the fields `append-issue` needs, not to number them.

**Bind `{extracted_story_keys}`** = the list of story keys extracted in this step (the
`key:` of each story removed from its sprint's story list, one per line), for **whichever**
source layout it came from. Empty is a normal result. This list feeds Stage E3's drift check
later — an extracted story's authored `.md` artifact is left in place (artifacts never move)
even though its state node no longer exists, and that is an *expected* consequence of this
step, not drift.

Record every normalization applied (node, old status, new status) for the final report; for
each extracted issue, record the assigned `BL-` key only after Stage C's `append-issue` call
returns it (parse it from the `OK append-issue {key} -> ...` line on stdout) — never before.
A legacy-per-epic source will usually record zero normalizations; that is the expected case,
not a reason to skip the step.

---

## Cross-reference normalization — `depends_on` and `superseded_by` (both source paths)

Two kinds of field store *another node's key* rather than the node's own identity:
`depends_on` (present on epic nodes — a list of epic keys — and on story nodes — a list of
story keys) and `superseded_by` (epic nodes only). Neither is touched by the `id:`→`key:`
conversion above, because that conversion only rewrites a node's *own* identity field — but
the values *inside* `depends_on`/`superseded_by` need the identical reformatting, or they
silently stop matching the keys the rest of this migration produces. This applies to
**both** source layouts, not just legacy flat — a legacy per-epic source is not guaranteed
to have had this normalization applied by whatever process produced it.

Apply this to the working epic list before Stage B writes anything:

- **Epic `depends_on` entries** and **`superseded_by` values** each reference another
  epic. Normalize each one exactly like the epic's own `id:`→`key:` conversion: strip any
  non-digit prefix, parse the remaining digits as an integer, zero-pad to 3 digits, prefix
  with `E`. Idempotent — an already-correct `'E003'` converts to itself, so it is always
  safe to apply this even to entries that look fine already.
- **Story `depends_on` entries** each reference another story via its full
  `E{nnn}-S{nn}-{nnn}` key. Normalize the three segments independently with the same
  rule — epic segment to 3 digits, sprint segment to 2 digits, sequence segment to 3
  digits.

Do not attempt to resolve these references here — that check needs the finished tree and
is Stage E4, below. This step only reformats the values Stage B is about to write.

---

## Stage B — explode the working epic list into sharded files (both source paths)

By this point you have one working epic list, in legacy per-epic shape (nested
`sprints:`/`stories:`), with every node's own identity and every cross-reference already
normalized to `key:` form, regardless of source. Explode it:

The status→folder mapping below is **total**: by the status-normalization step above, every
epic in the working epic list carries one of exactly three statuses, and each of the three
has a destination. There is no fourth case to improvise a folder for. The `else` branch is a
belt-and-braces assertion — it should be unreachable, and if it ever fires the correct
response is to halt, not to guess:

```
for each epic node in the working epic list:
    if   epic.status == "backlog":     status_dir = "planned"
    elif epic.status == "in-progress": status_dir = "active"
    elif epic.status == "done":        status_dir = "archived"
    else:                              HALT (see below) — do not create any directory
    mkdir -p {pm_state_root}/{status_dir}/epic-{nnn}/
    write {pm_state_root}/{status_dir}/epic-{nnn}/epic.yaml
    for each sprint node in epic.sprints:
        mkdir -p {pm_state_root}/{status_dir}/epic-{nnn}/sprint-{nn}/
        write .../sprint-{nn}/sprint.yaml
        for each story node in sprint.stories:
            write .../sprint-{nn}/{story-key}.yaml
```

`{nnn}` is the epic number zero-padded to 3 digits, taken from the epic's `key: 'E{nnn}'`
(e.g. `key: 'E003'` → directory `epic-003`). `{nn}` is the sprint number zero-padded to 2
digits, taken from the sprint's `key: 'S{nn}'` (e.g. `key: 'S01'` → directory
`sprint-01`). By Stage A / the legacy per-epic load above, every epic and sprint already
carries a `key:` in this exact format — there is no separate padding computation to do
here beyond reading it back out of `key:`.

If the `else` branch is reached — an epic status that is not one of the three — halt
immediately with the same message the status-normalization step uses, and remove any
directories this stage created so far so the retry meets a clean `{pm_state_root}`:

```
BLOCKED: epic {key} has status '{status}', which has no destination folder. This should
have been caught by status normalization; nothing further was written. Fix the source
node's status and re-run migrate-state.
```

Sprint and story nodes carry no folder of their own (they live inside their epic's
directory), so they need no mapping here — but their statuses were normalized by the same
step, so they too are guaranteed to be values `pm-status.py` will accept.

**Every node is written bare — no `epics:` list wrapper anywhere in the sharded layout.**

### `epic.yaml` contents

The epic node **minus** its `sprints:` list. Field order, matching the PM skills'
`references/status-files.md` example:

```yaml
key: 'E003'
title: 'Epic 003 — ...'
goal: '...'
status: in-progress
depends_on: [...]          # only if present on the source node; already normalized above
superseded_by: '...'       # only if this epic was normalized from `superseded`; already normalized above
estimate:
  ...                      # copied verbatim if present
actual:
  ...                      # copied verbatim if present
```

Do not write a `_lock:` block — locks are runtime-only, written by `l3io-pm-execute` when
it claims an epic; migration never fabricates one. Preserve any other fields found on the
source epic node verbatim, in their original relative order, appended after the fields
above.

### `sprint.yaml` contents

The sprint node **minus** its `stories:` list, **plus** an `epic:` back-reference:

```yaml
key: 'S01'
epic: 'E003'                # back-reference to the parent epic — must match the directory
title: 'Sprint 01 — ...'
status: in-progress
estimate:
  ...
actual:
  ...
```

### `{story-key}.yaml` contents

The story node, **plus** `epic:` and `sprint:` back-references:

```yaml
key: 'E003-S01-002'
epic: 'E003'
sprint: 'S01'
title: '...'
status: review
classification: ...
estimate:
  ...
actual:
  ...
completion_evidence:        # only if present (status: done stories)
  ...
depends_on: [...]           # only if present on the source node; already normalized above
```

File name is `{story-key}.yaml` exactly (e.g. `E003-S01-002.yaml`), placed inside the
sprint directory alongside `sprint.yaml`.

Preserve every other field found on each source node verbatim — this stage reshapes
structure (dropping list wrappers, adding back-references, renaming `id:`→`key:` and
normalizing cross-references where the steps above already did that work) but never
invents or drops data values.

---

## Stage C — issues and calibration

### Issues

**Legacy flat source:** Write `{pm_issues_file}` (`{pm_state_root}/issues.yaml`) with the
pre-existing backlog items from the working issues list, as-is, under a `backlog:` key:

```yaml
backlog:
  - key: 'BL-E001-004'      # every pre-existing item, copied verbatim, keys unchanged
    ...
```

Then, for each deferred-story extraction recorded in the status-normalization step, append it through the real
CLI writer rather than hand-authoring its shape a second time — this is the one case in
this migration where the destination file already exists and has real schema-validation
value:

```bash
uv run {pm_status} append-issue --file {pm_issues_file} \
  --epic {epic_num_3digit} --sprint {sprint_num_2digit_or_empty} \
  --title "{story_title}" --source "migrate-state (deferred)" --severity Low
```

(`--epic`/`--sprint` take bare zero-padded numbers, no `E`/`S` prefix, e.g. `--epic 003
--sprint 01` — matching the same numbers used for the directory names above.) If `uv` is
unavailable, use `python3 {pm_status} ...` instead.

**Legacy per-epic source:** Copy `{project-root}/_bmad/state/sprint-status-issues.yaml` to
`{pm_issues_file}` unchanged — its schema is already correct, no transformation needed.

### Calibration

If `{project-root}/_bmad/pm-calibration.yaml` exists (either source layout — this file
lives at the project-root level, independent of which sprint-status layout was in use),
copy it to `{pm_calibration_file}` (`{pm_state_root}/pm-calibration.yaml`). It is now
committed team knowledge rather than gitignored local data, per the project's state
layout contract — do not add it to `.gitignore`.

If it does not exist, skip — no file is created.

**Nothing has been removed or backed up yet at this point.** The legacy originals are
still exactly where they were before this procedure started; only new files under
`{pm_state_root}` have been written. Stage D creates backups next (still non-destructive);
Stage E then verifies the new tree; only Stage F, after Stage E passes, touches the
originals.

---

## Stage D — create backups (non-destructive; originals are untouched by this stage)

**Never overwrite an existing `.legacy` backup — a second migration run must not destroy
the first run's backup.** Check for the `.legacy` target first, every time.

**Legacy flat source** — for each of the three flat files that exists:
```bash
[ ! -f {implementation_artifacts}/sprint-status.yaml.legacy ] && \
  cp {implementation_artifacts}/sprint-status.yaml \
     {implementation_artifacts}/sprint-status.yaml.legacy
[ ! -f {implementation_artifacts}/sprint-status-backlog.yaml.legacy ] && \
  cp {implementation_artifacts}/sprint-status-backlog.yaml \
     {implementation_artifacts}/sprint-status-backlog.yaml.legacy
[ ! -f {implementation_artifacts}/sprint-status-archived.yaml.legacy ] && \
  cp {implementation_artifacts}/sprint-status-archived.yaml \
     {implementation_artifacts}/sprint-status-archived.yaml.legacy
```
(run only for files that exist.)

**Legacy per-epic source** — back up the whole tree as one directory copy:
```bash
[ ! -d {project-root}/_bmad/state.legacy ] && \
  cp -r {project-root}/_bmad/state {project-root}/_bmad/state.legacy
```

**Both sources**, if `{project-root}/_bmad/pm-calibration.yaml` exists:
```bash
[ ! -f {project-root}/_bmad/pm-calibration.yaml.legacy ] && \
  cp {project-root}/_bmad/pm-calibration.yaml \
     {project-root}/_bmad/pm-calibration.yaml.legacy
```

This stage only ever adds `.legacy` copies. It never removes anything under an original
name — that only happens in Stage F, and only after Stage E passes.

---

## Stage E — verify before touching any original (all four checks required; gates Stage F)

At this point: the sharded tree exists at `{pm_state_root}`, `.legacy` backups exist
alongside the originals, and **the originals themselves are still fully intact and
untouched**. Every check below reads only the newly-written sharded tree (plus, for E3,
the artifact tree it never modifies, and for E4, the sharded tree's own recorded keys) —
none of them need the legacy originals to still be present, so there is no reason to defer
them past this point, and no reason to run the one destructive stage (F) before they've
all passed.

**If any check below fails, halt immediately — do not run Stage F.** Print exactly what
failed. Nothing has been removed: the legacy originals are exactly where Stage D found
them, and the `.legacy` backups created in Stage D are additionally present. A retry
requires resolving the failure and re-running migrate-state; note that Pre-flight will
then find the (partial) sharded tree at `{pm_state_root}` and block on it — clear or fix
that tree by hand before retrying, per the Pre-flight `SHARDED=1` message.

### E1 — state root must be tracked by git, not ignored

```bash
git -C {project-root} check-ignore -q {pm_state_root} && echo "FAIL: gitignored" || echo "OK: tracked"
```

If this reports `FAIL`, the migration just wrote the project's state somewhere it will be
silently lost on the next `git clean` or simply never get committed. Report this **loudly**
— it is a correctness failure, not a warning to note in passing:
```
CRITICAL: {pm_state_root} is gitignored. The migrated state will not be committed. Add a
negation rule to .gitignore before doing anything else:
  !{pm_state_root}/
  !{pm_state_root}/**
```
E1 passes only when `check-ignore` reports `OK: tracked`.

### E2 — structural / back-reference integrity, per migrated epic

For every epic key produced in Stage B:

```bash
uv run {pm_status} verify --state-root {pm_state_root} --epic {epic_key} --scope epic
```

`--scope epic` walks every `sprint-{nn}/` directory it finds under the epic and checks two
things: that each one contains a `sprint.yaml`, and that every sprint and story file in the
tree carries `epic:`/`sprint:` back-references matching the directory it was found in — an
**absent** back-reference fails just as a mismatched one does, which is what makes this a
real gate on Stage B's newest transformation (Stage B is where those back-references first
come into existence). It does **not** check completion status, so an in-progress epic with
non-`done` stories is expected to pass.

What it cannot tell you: whether a story Stage B *should* have written is missing. There is
no manifest of expected stories on disk — the directory listing *is* the list — so a story
dropped between the working epic list and the write simply looks like a sprint with fewer
stories. E3 below is what catches that, by diffing state files against story artifacts.
If `uv` is
unavailable, use `python3 {pm_status} ...` instead. E2 passes only when every migrated
epic's `verify` call exits 0.

### E3 — drift: state files vs story artifacts, per sprint

Only for epics under `active/` and `archived/`. A `planned/` epic legitimately has state
with no artifacts yet (stories are authored after planning, not before) — that is not
drift, and must not be checked.

The artifact tree's epic directory may still be at its pre-sharded padding width
(`epic-01`, 2-digit) — the "epic-directory padding reconciliation" that would rename these
to match the state tree's 3-digit `epic-{nnn}` is a separate, later cleanup and must not be
assumed done here. Resolve the artifact epic directory **numerically**, not by fixed-width
string match. Also, **a deferred story extracted by status normalization is expected to show up as an
artifact-only orphan** — its `.md` file is still there (artifacts never move) but it
correctly has no state file any more (it lives in `issues.yaml` instead). Suppress those
against `{extracted_story_keys}` and report them separately, not as drift:

```bash
for epic_dir in {pm_state_root}/active/epic-*/ {pm_state_root}/archived/epic-*/; do
  [ -d "$epic_dir" ] || continue
  epic_num=$(basename "$epic_dir" | sed 's/^epic-0*//')
  # find the matching artifact epic dir regardless of its zero-padding width
  artifact_epic_dir=""
  for d in {implementation_artifacts}/epic-*/; do
    [ -d "$d" ] || continue
    n=$(basename "$d" | sed 's/^epic-0*//')
    [ "$n" = "$epic_num" ] && artifact_epic_dir="$d" && break
  done

  for sprint_dir in "$epic_dir"sprint-*/; do
    [ -d "$sprint_dir" ] || continue
    sprint_name=$(basename "$sprint_dir")   # sprint-NN — same width in both trees

    state_stories=$(ls "$sprint_dir"*.yaml 2>/dev/null | xargs -n1 basename \
                     | grep -v '^sprint\.yaml$' | sed 's/\.yaml$//' | sort)
    artifact_stories=""
    if [ -n "$artifact_epic_dir" ]; then
      artifact_stories=$(ls "${artifact_epic_dir}${sprint_name}/stories/"*.md 2>/dev/null \
                          | xargs -n1 basename | sed 's/\.md$//' | sort)
    fi

    # state-only: has a state file, no artifact — this direction is never caused by a
    # deferred-story extraction (extraction removes the state file, not the artifact),
    # so it is always genuine drift.
    state_only=$(comm -23 <(echo "$state_stories") <(echo "$artifact_stories"))
    printf '%s\n' "$state_only" | while IFS= read -r key; do
      [ -z "$key" ] && continue
      echo "DRIFT (state present, artifact missing): $key — epic $epic_num $sprint_name"
    done

    # artifact-only: has an artifact, no state file — expected if it was extracted as a
    # deferred-story issue during status normalization; genuine drift otherwise.
    artifact_only=$(comm -13 <(echo "$state_stories") <(echo "$artifact_stories"))
    printf '%s\n' "$artifact_only" | while IFS= read -r key; do
      [ -z "$key" ] && continue
      if printf '%s\n' "${extracted_story_keys}" | grep -qxF "$key"; then
        echo "EXPECTED (deferred-story extraction, not drift): $key — epic $epic_num $sprint_name"
      else
        echo "DRIFT (artifact present, state missing): $key — epic $epic_num $sprint_name"
      fi
    done
  done
done
```

Report the `EXPECTED` bucket separately, with wording that makes clear it is a normal,
expected consequence of the status-normalization step's deferred-story extraction — not something to
investigate. Never auto-correct either `DRIFT` direction — a genuine orphan on either side
needs a human decision:
- `DRIFT (state present, artifact missing)` — the artifact was never created, was moved,
  or was deleted after the story was marked done.
- `DRIFT (artifact present, state missing)` — the story was authored outside
  `pm-status.py` and never got a state node, or its state node landed in the wrong sprint
  directory.

E3 passes only when the `DRIFT` bucket (either direction) is empty. A non-empty `EXPECTED`
bucket does not fail E3.

### E4 — cross-reference resolution (`depends_on`, `superseded_by`)

Build the full set of keys now present in the sharded tree: every `epic.yaml`'s `key:`,
and every story file's `key:` (every `{story-key}.yaml` under every migrated epic/sprint).

For every epic's `depends_on:` entry and `superseded_by:` value, and every story's
`depends_on:` entry — all already normalized to `key:` form by the step before Stage B —
check whether it is present in that set. Anything not present is unresolved:
```
{referencing node key} → {field}: {target key} — UNRESOLVED (no migrated node with this key)
```
**Never drop or blank an unresolved reference** — the file keeps the normalized value
exactly as written; the target may simply be an epic or story that was out of scope for
this migration. Report it for a human to resolve. E4 passes only when this list is empty.

---

### Stage E gate

All four checks must pass to proceed:
```
E1 gitignore check:    {OK | FAIL}
E2 structural verify:  {N}/{N} epics passed
E3 drift:              {none found | N genuine orphan(s) — see report} (expected/suppressed: {N})
E4 cross-references:   {none unresolved | N unresolved — see report}
```

If all four are clean, continue to Stage F. Otherwise:
```
BLOCKED: migration verification failed — nothing was removed. The sharded tree at
{pm_state_root} is on disk but has not been trusted with the destructive next step yet.
Your original legacy files are untouched at their original locations, and the Stage D
backups are additionally present at the paths listed below. Fix the following before
re-running:
  {every failed check, with its detail}
Legacy originals (untouched):  {list}
Legacy backups (Stage D, also untouched): {list}
```
Stop here. Do not proceed to Stage F.

---

## Stage F — remove originals and dispose of backups (only after Stage E passes in full)

### F1 — verify each backup exists, then clear the original

For each backup created (or already present) in Stage D, confirm it exists on disk (`[ -e
{backup} ]`) **before** removing the corresponding original. This ordering is deliberate:
nothing under the original name is removed until a verified-present `.legacy` copy exists,
and by this point Stage E has already confirmed the sharded tree it will be replacing them
with is correct.

The originals must be fully removed (not overwritten with an empty stub) — leaving
anything at the plain `sprint-status.yaml` / `_bmad/state/` path would make a future
`step-00-activate.md` three-way count misdetect a legacy layout as still present, even
though it is empty:

```bash
# legacy flat
rm -f {implementation_artifacts}/sprint-status.yaml \
      {implementation_artifacts}/sprint-status-backlog.yaml \
      {implementation_artifacts}/sprint-status-archived.yaml
# legacy per-epic
rm -rf {project-root}/_bmad/state
# both, if pm-calibration.yaml existed
rm -f {project-root}/_bmad/pm-calibration.yaml
```

### F2 — ask what to do with the `.legacy` backups

The `.legacy` files/directory themselves are untouched by F1 — only their un-suffixed
originals were removed. Ask:

```
What would you like to do with the legacy backup files?
  M — move to {project-root}/_bmad/migration-backup/ (recommended)
  D — delete them
  K — keep in place (the health check will offer cleanup later)
[M]:
```

**If M (default):**
```bash
mkdir -p {project-root}/_bmad/migration-backup
mv {implementation_artifacts}/sprint-status*.yaml.legacy \
   {project-root}/_bmad/state.legacy \
   {project-root}/_bmad/pm-calibration.yaml.legacy \
   {project-root}/_bmad/migration-backup/ 2>/dev/null
```
(move only whichever of these paths actually exist.) Print: `Legacy files moved to
{project-root}/_bmad/migration-backup/`

**If D:** print a confirmation warning first — this is the one irreversible choice in
this procedure:
```
This permanently deletes the only backup of the pre-migration state. Type DELETE to confirm:
```
On confirmation:
```bash
rm -f {implementation_artifacts}/sprint-status*.yaml.legacy \
      {project-root}/_bmad/pm-calibration.yaml.legacy
rm -rf {project-root}/_bmad/state.legacy
```
Print: `Legacy files deleted.`

**If K:** print `Legacy files left in place. Run /l3io-util-doctor clean-legacy to remove
them later.` — no changes.

---

## Final report

Per epic migrated, report:
```
Epic {key} — {title}
  Destination: {planned|active|archived}
  Sprints:     {N}
  Stories:     {N}
  Drift:       none | {list of genuine orphaned story keys, both directions}
  Expected (deferred-story extraction): none | {list of story keys}
```

Then:
```
migrate-state complete:
  Epics migrated:         {N} ({destination breakdown by folder})
  Issues carried over:    {N} pre-existing + {N} extracted from deferred stories
  Calibration migrated:   yes | no (no pm-calibration.yaml found)
  E1 gitignore check:     OK
  E2 structural verify:   {N}/{N} epics passed
  E3 drift:               none found (expected: {N} deferred-story extraction(s))
  E4 cross-references:    none unresolved
  Legacy backups:         moved to migration-backup/ | deleted | kept in place
```

---

```
Next steps:
  Run /l3io-pm-plan to rebuild the execution plan against the new state layout.
```
