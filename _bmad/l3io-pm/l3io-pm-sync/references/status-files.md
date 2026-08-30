# Status File Layout Contract (sharded state tree)

Communicate all responses in `{communication_language}`.

This file is the single source of truth for **where** epic/sprint/story/backlog state lives
on disk and **how** to read or write it. It is a **deep reference, consulted on demand** — do
not load it at activation. `steps/shared/step-00-digest.md` carries the operative digest
every run needs (keys, subcommand signatures, exit codes) plus a routing table naming the
section to read for each case that genuinely needs this file: a `verify` failure (§7), a
per-file schema question (§4), a migration or legacy layout (§10), `depends_on` (§11), or an
epic lock question (§6).

This file outranks the digest. Where they disagree, this file is correct — and `pm-status.py`
outranks both, since it enforces these rules mechanically.

State is addressed through `pm-status.py` by **key**, never by hand-built path. No skill or
step file should construct a state path itself — see "Addressing" below.

## 1. File locations

All l3io-pm state lives under `{implementation_artifacts}/state/` — committed to git,
co-located with the artifacts it describes. Nothing state-related lives under
`{project-root}/_bmad/` any more; that tree is installer-owned and gitignored.

```
{implementation_artifacts}/
│
├── state/                                   ← machine-written, pm-status.py only
│   ├── planned/
│   │   └── epic-005/
│   │       ├── epic.yaml                    ← depends_on lives here
│   │       └── sprint-01/
│   │           ├── sprint.yaml
│   │           └── E005-S01-001.yaml
│   ├── active/
│   │   ├── epic-001/
│   │   │   ├── epic.yaml
│   │   │   ├── sprint-01/
│   │   │   │   ├── sprint.yaml
│   │   │   │   ├── E001-S01-001.yaml
│   │   │   │   ├── E001-S01-002.yaml
│   │   │   │   └── E001-S01-003.yaml
│   │   │   └── sprint-02/
│   │   │       ├── sprint.yaml
│   │   │       └── E001-S02-001.yaml
│   │   └── epic-004/…
│   ├── archived/
│   │   └── epic-002/…                       ← done; keeps its full tree
│   ├── issues.yaml                          ← flat BL list
│   ├── events.jsonl                         ← append-only transition log
│   ├── pm-calibration.yaml
│   └── adr-register.yaml                    ← ADR number allocator (`next`, `reserved`)
│
├── epic-001/                                ← human/agent-authored artifacts
│   ├── sprint-01/
│   │   ├── stories/
│   │   │   ├── E001-S01-001.md
│   │   │   ├── E001-S01-002.md
│   │   │   └── E001-S01-003.md
│   │   ├── closure/
│   │   └── tests/
│   ├── sprint-02/…
│   ├── tests/
│   └── epic-closure/
├── epic-002/…                               ← artifacts persist after close; never move
└── epic-004/…
                                             ← no epic-005/ — nothing authored until work starts
```

An epic's directory lives in exactly one of `planned/`, `active/`, or `archived/` at any
time (see "Placement rule" below). Every sprint and story of that epic lives inside the same
epic directory, one file per node.

`events.jsonl` is an append-only JSON-lines log — one object per status or actuals write,
appended automatically by `set-status`/`set-actual` under `flock`. It is the only place
per-status *dwell* time can come from: `updated_at` records just the last write and is
overwritten by any field change, so it cannot distinguish "entered review 20 minutes ago"
from "had its estimate patched 20 minutes ago". It is committed, and it is one
project-level log rather than one per sprint — per-sprint files would fragment the timeline
and turn cross-epic velocity into a multi-file join. Absent on projects that predate it, in
which case `report` falls back to `updated_at` and marks those dwell figures approximate
with a `~` prefix. Never read it to determine current status; the node files are
authoritative for that, and the log is history.

## 2. The two trees

`state/` and the top-level `epic-{nnn}/` directories hold two different *kinds* of fact
about the same epic. They are not duplicates of each other.

| | `state/{status}/epic-001/` | `epic-001/` (top level) |
|---|---|---|
| Holds | Status, estimates, actuals, locks | Story markdown, closure reports, QA tests, ADRs |
| Written by | `pm-status.py` only, atomically | Humans and `bmad-dev-story` / review agents |
| Format | YAML metadata | Prose, code, test files |
| Moves? | Yes — `planned/` → `active/` → `archived/` | Never. Created once, stays forever |
| Answers | "What state is it in?" | "What is it?" |

Two asymmetries follow, both correct:

- **A planned epic has state but no artifacts.** Status and estimates exist before any
  story is authored. State comes into existence first.
- **A done epic keeps both, permanently.** Artifacts never move on close, which is why
  state must not collapse on close either — otherwise the mirror holds for active epics and
  breaks for finished ones.

**Every epic with artifacts has state; not every epic with state has artifacts yet.**

## 3. Key schema

- Epic key: `E{nnn}` (3-digit zero-padded string, e.g. `"E001"`) → directory `epic-{nnn}`
- Sprint key: `S{nn}` (2-digit zero-padded string, e.g. `"S01"`) → directory `sprint-{nn}`
- Story key: `E{nnn}-S{nn}-{nnn}` (globally unique, e.g. `"E001-S02-003"`) → file
  `E{nnn}-S{nn}-{nnn}.yaml` inside that sprint's directory
- Backlog item key: `BL-E{nnn}-{nnn}` (e.g. `"BL-E001-001"`; `BL-E000-{nnn}` for repo-global).
  The trailing `{nnn}` is **allocated by `append-issue` itself, under a lock — never chosen
  by the caller.** No step file, reference, or digest binds this number anywhere else; a
  caller that invented it was the exact defect this replaces (two agents inventing the same
  next number simultaneously, the same collision class production ADR numbers hit before
  `adr-reserve` existed). Pass `--key` only to name an existing item explicitly — an
  explicit key that already exists is refused (exit 2), not silently reassigned.

Node fields use `key:` (not `id:`) in every file.

## 4. Per-file schema

Sharding splits a nested tree into files, so each file's contents are specified below.

**Nodes are stored bare — no `epics:` list wrapper.** The wrapper existed only when one file
held many epics. With one node per file it is pure noise, and removing it lets `set-field`
dot-paths address node fields directly.

**The directory structure replaces the `sprints:` and `stories:` lists.** This is the
largest schema consequence of sharding: `epic.yaml` has no `sprints:` key and `sprint.yaml`
has no `stories:` key. Children are discovered by listing the directory — sprint
subdirectories under an epic, story `.yaml` files (excluding `sprint.yaml`) under a sprint.

**Child files carry a back-reference to their parents** (`epic:` on sprint and story files,
`sprint:` also on story files). The path already encodes this, so it is redundant —
deliberately. It makes each file self-describing when read standalone or matched by grep,
and it lets `verify --scope epic` catch a file sitting in the wrong directory by comparing
its path against its contents.

```yaml
# state/active/epic-001/epic.yaml
_lock:                                    # machine metadata, underscore-prefixed, first key
  session_id: 'l3io-pm-2026-08-16T10:00:00-abc123'
  claimed_at: '2026-08-16T10:00:00'
  ttl_minutes: 30
key: 'E001'
title: 'Epic 001 — Foundation'
goal: 'Stand up the core platform'
status: in-progress
depends_on: []                            # epic keys; read by l3io-pm-plan
estimate:                                 # ranges at epic/sprint level
  man_hours_low: 40
  man_hours_high: 60
  hitl_hours_low: 6
  hitl_hours_high: 10
  elapsed_hours_low: 8
  elapsed_hours_high: 12
  tokens_k_min: 2000
  tokens_k_max: 3200
  cost_low: 8.25                          # derived from tokens_k_min/max x rates; never entered
  cost_high: 13.20
  model: claude-opus-5                    # the rate card that priced the range
  confidence: medium
actual:                                   # METRIC_FIELDS — all five required
  elapsed_hours: 11.5
  man_hours: 52                           # counterfactual re-assessment, not observed
  hitl_hours: 7.2
  tokens_k: {total: 2840, input: 420, output: 140, cache_write: 850, cache_read: 1430}
  cost: 6.98                              # derived; written by the tool, never by hand
  model: claude-sonnet-5
orchestration:                            # sprint/epic only — the orchestrator's own overhead
  elapsed_hours: 0.6
  man_hours: 0                            # AI-only overhead; no human-developer counterfactual
  hitl_hours: 0.1
  tokens_k: {total: 90, input: 14, output: 5, cache_write: 27, cache_read: 44}
  cost: 0.23
  model: claude-sonnet-5
orchestration_sampled_at: '2026-08-16T22:34:03Z'  # replay guard; set-actual --block orchestration
# no `sprints:` — sprint-NN/ directories are the list
```

```yaml
# state/active/epic-001/sprint-01/sprint.yaml
key: 'S01'
epic: 'E001'                              # back-reference; path must agree
title: 'Sprint 01 — Foundation'
status: in-progress
estimate:
  man_hours_low: 12
  man_hours_high: 18
  hitl_hours_low: 1.5
  hitl_hours_high: 2.5
  elapsed_hours_low: 2.5
  elapsed_hours_high: 4
  tokens_k_min: 600
  tokens_k_max: 950
  cost_low: 2.48                          # derived; never entered
  cost_high: 3.93
  model: claude-opus-5                    # the rate card that priced the range
  confidence: high
actual:
  elapsed_hours: 3.2
  man_hours: 15                           # counterfactual re-assessment, not observed
  hitl_hours: 1.8
  tokens_k: {total: 812, input: 122, output: 41, cache_write: 244, cache_read: 405}
  cost: 2.02
  model: claude-sonnet-5
# no `stories:` — E001-S01-*.yaml files are the list
```

```yaml
# state/active/epic-001/sprint-01/E001-S01-003.yaml
key: 'E001-S01-003'
epic: 'E001'                              # back-references; path must agree
sprint: 'S01'
title: 'Implement token ledger'
status: review
classification: complex
estimate:                                 # single values at story level
  man_hours: 6
  hitl_hours: 0.8
  elapsed_hours: 1.5
  tokens_k: {total: 320, input: 48, output: 16, cache_write: 96, cache_read: 160}
  cost: 1.32                              # derived; never entered
  model: claude-opus-5
  confidence: high
actual:
  elapsed_hours: 1.8
  man_hours: 7                            # counterfactual re-assessment, not observed
  hitl_hours: 0.5
  tokens_k: {total: 355, input: 53, output: 18, cache_write: 107, cache_read: 177}
  cost: 1.47
  model: claude-opus-5
```

`_lock` (epic files only) is machine metadata and is always the first key when present —
see "Ownership lock" below.

## 5. Placement rule

**An epic's directory lives in the folder named for its status.** A node lives in exactly
one place at any time; never duplicate a node. Every transition is a directory move:

```
planned/epic-005/  →  active/epic-005/  →  archived/epic-005/
```

There is no separate archive-on-close operation that reshapes data — `archive-epic` is a
directory move, nothing else. The directory name never changes, only its parent folder, so
`git log --follow` keeps working on every file in the tree across every transition.

Sprints and stories never move independently of their epic — they travel with the epic
directory that contains them.

## 6. Ownership lock

When `l3io-pm-execute` claims an epic, `pm-status.py set-lock` writes a `_lock` block as the
**first key** of that epic's `epic.yaml`:

```yaml
_lock:
  session_id: "claude-session-abc123"
  claimed_at: "2026-08-13T14:30:00Z"
  ttl_minutes: 30
```

`set-lock` itself enforces mutual exclusion — it is not a bare write gated by a separate
check. The whole read-existing-lock → decide → write-claim cycle runs under one exclusive
lock (`epic_node_lock`) so two callers can never both read "free" and both write a claim:

```bash
uv run {pm_status} set-lock --state-root {pm_state_root} --epic E001 --session-id {session_id} --ttl-minutes 30
```

- **No existing `_lock`** — claim. Exit `0`.
- **Existing `_lock`, same `session_id`** — re-claim/refresh (`claimed_at` reset to now).
  Exit `0`. A retry by the owner must not deadlock or refuse against its own lock.
- **Existing `_lock`, different `session_id`, TTL expired** (age past `claimed_at` exceeds
  `ttl_minutes`) — takeover: claim, and the success message names the previous holder and
  how stale the lock was. Exit `0`.
- **Existing `_lock`, different `session_id`, TTL still live** — refuse. The file is left
  untouched. Exit `5`, naming the holder and the minutes remaining.
- **Existing `_lock` present but malformed** — not a mapping, missing `claimed_at`, or a
  `claimed_at` that fails to parse — refuse rather than treat it as absent or stealable: a
  lock that cannot be read is not a lock that may be taken over. Exit `5`.

Check without claiming:

```bash
uv run {pm_status} check-lock --state-root {pm_state_root} --epic E001 --session-id {session_id}
```

- Exit `0` — free (no lock, held by this same session, or stale past its TTL).
- Exit `5` — locked by another session within its TTL.

`check-lock` is read-only — it answers "could I claim this" without writing anything, and
takes no lock of its own around the read since nothing but a report depends on it. Only
`set-lock` performs the claim and needs `epic_node_lock` to make check-then-act atomic.

**Missing-epic asymmetry, deliberate and tested:** `check-lock` and `clear-lock` treat a
nonexistent epic as absent and exit `0` (`check-lock` prints `FREE`; `clear-lock` is a
no-op) — both are queries/cleanup, so "there's nothing to lock/unlock" is success, not an
error. `set-lock` exits `3` (node not found) on a nonexistent epic, because it must have a
file to write the lock into — this is distinct from, and takes priority over, the exit `5`
refusal above, which only applies once the epic file exists and its `_lock` can be
evaluated. Do not "fix" this into uniform behavior — it was deliberately introduced (and
tested) as three different contracts for three different verbs.

## 7. Addressing

**All node operations go through `pm-status.py` with `--state-root` plus node keys. Skills
never construct state paths themselves.** Layout knowledge lives in exactly one place —
`pm-status.py` — so a future layout change only touches that script, not every step file.

```bash
# epic node
uv run {pm_status} set-status --state-root {pm_state_root} --epic E001 --status in-progress

# sprint node (epic + sprint key together)
uv run {pm_status} set-status --state-root {pm_state_root} --epic E001 --sprint S01 --status in-progress

# story node (story key alone is enough — it encodes epic + sprint)
uv run {pm_status} set-status --state-root {pm_state_root} --story E001-S01-003 --status done
```

`pm-status.py` resolves `E001-S01-003` to
`{pm_state_root}/{planned|active|archived}/epic-001/sprint-01/E001-S01-003.yaml`, searching
the three status folders (`active` first, as the hottest path). The same resolution applies
to `--epic`/`--sprint` pairs. No caller ever supplies a raw path for a node.

**One exception: `append-issue`.** `issues.yaml` is a flat file, not a resolvable node — it
has no epic/sprint/story key of its own to resolve from — so `append-issue` is the one
subcommand that still takes `--file`:

```bash
uv run {pm_status} append-issue --file {pm_issues_file} \
  --epic 001 --title "..." --source "..." --severity Medium
```

`--key` is omitted here deliberately — it is optional, and when omitted `append-issue`
allocates the next `BL-E001-{nnn}` itself (see §3). Pass `--key` only when you mean to name
an existing item; an explicit key that already exists is refused (exit 2), not renumbered.

`append-issue` always runs its whole load → allocate-key → dedupe-check → mutate → save
cycle under one exclusive lock (it is the last remaining shared-append target — see
"Concurrency" below); this is automatic, not a flag. A content duplicate — the same
normalized title, epic, sprint, and source as an existing item — is skipped (exit 0,
nothing written) unless `--allow-duplicate` is passed.

Subcommand summary (see `pm-status.py --help` for full flags):

| Subcommand | Addressing |
|---|---|
| `set-status`, `set-actual`, `set-estimate`, `set-field`, `verify` | `--state-root` + (`--story KEY` \| `--epic ID [--sprint ID]`) |
| `set-actual` extra | `--block {actual,orchestration}` (default `actual`); `orchestration` writes the orchestrator's own overhead and is valid on a sprint or epic only, never a story |
| `estimate-story` | `--state-root --story KEY --classification {simple,standard,complex} [--confidence ...] [--model ID] [--token-rates JSON]` — computes and writes a story's estimate block from `BASE_BANDS` × calibrated scope ratio × fix factor, per metric, then prices `cost` from the estimated `tokens_k` |
| `estimate-rollup` | `--state-root --epic ID [--sprint ID] [--model ID] [--token-rates JSON]` — sums child estimates and writes the parent's range-form estimate, widened by the calibrated (or cold-start) closure band and the calibrated (or unseeded) orchestration band, then prices `cost` from the rolled-up `tokens_k` range |
| `show` | `--state-root --epic ID [--sprint ID]` — renders a computed roll-up, plus a `spend/` breakout by story / closure / orchestration |
| `set-lock`, `clear-lock`, `check-lock` | `--state-root --epic ID` (epic only — locks apply to epics) |
| `move-epic` | `--state-root --epic ID --to {planned,active,archived}` |
| `archive-epic` | `--state-root --epic ID` — alias for `move-epic --to archived` |
| `append-issue` | `--file` (the one exception; see above) |
| `list-issues` | `--state-root` (reads `{state-root}/issues.yaml`) + optional `--epic`/`--sprint`/`--severity`/`--format` filters |
| `calibration show` \| `migrate-metrics` \| `redrive` | `--state-root [--format {text,json}]` — `show` is a read-only report of every component's sample count and active ratio (a missing file reports cold-start and exits `0`); `migrate-metrics` reshapes a pre-metrics-rework calibration file in place (gated on its own marker, idempotent); `redrive` re-derives calibration samples from the story files already on disk (`redrive_story_samples`), for backfilling or repairing samples without re-running the work |
| `report` | `--state-root` (+ optional `--plan` pointing at `plan-output-meta.yaml`, `--stall-minutes N`) — walks every epic in every status folder; addresses none individually. Read-only unless `--out` is given. `--status planned,active,archived` narrows the display (default `planned,active`); counting is unaffected. Flags any dispatch opened longer than `--stall-minutes` (default 15) and never closed. Every format carries a **Spend** section attributing actual spend to story / closure / orchestration (metrics-contract.md §6) |
| `dispatch` | `--state-root --event {open,close} --agent NAME` + optional `--epic`/`--sprint`/`--story`/`--session-id` — records a subagent dispatch boundary into `events.jsonl`; the input to `report`'s stalled-dispatch flags |
| `rates` | `[--model ID] [--token-rates JSON]` — prints the effective per-model token rate table (read-only); an unknown `--model` exits 2 |

`set-status` and `set-actual` both append a line to `state/events.jsonl` as a side effect of
a successful write (`--no-events` suppresses it, `--session-id` stamps it). A failed append
warns on stderr and never fails the write — the node file is the primary record and telemetry
must not be able to block it.

This replaced an optional `--ledger` flag and a `progress` subcommand, both removed. Because
the flag was opt-in and no step file ever passed it, no project ever produced a ledger; the
event log is unconditional so it cannot be silently skipped.

`set-actual` also derives and appends a calibration sample as a side effect of a successful
write (`--no-calibrate` suppresses it) — see `references/calibration-model.md` for what it
computes and why a failed derivation only warns rather than failing the actuals write.

`show --state-root {pm_state_root} --epic E001 [--sprint S01]` renders a computed roll-up
(status, story counts by status, summed actuals) from the child files on disk. It replaces
the old ability to read a whole sprint or epic out of one file. It is **not** a generated
file that gets committed — it is a read-only report to stdout.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success / verified |
| `2` | Usage error |
| `3` | Node not found |
| `4` | Verification failure (missing/invalid field, or structural mismatch) |
| `5` | Epic locked by another session |

### `verify` — two different checks behind one subcommand

`verify --scope epic` and `verify --scope {story,sprint}` check **different things**; do not
assume they are the same test at a different granularity.

- **`--scope epic`** walks the epic's whole subtree (its `epic.yaml`, every `sprint-{nn}/`
  directory, every file in them) and checks **structural / back-reference integrity**: every
  sprint directory must contain a `sprint.yaml`, and every sprint and story file must carry
  `epic:`/`sprint:` back-references that match the directory it was found in. A **missing**
  back-reference fails exactly like a mismatched one — a self-describing file that does not
  describe itself is not verified, and `migrate-state` writes those back-references for the
  first time, so "absent" is the case this most needs to catch. It does **not** check
  completion status — an in-progress epic legitimately contains stories that are not `done`,
  and this scope must not fail on that. Nor can it detect a story file that was never
  written: the directory listing is the only list of children there is (§4), so there is
  nothing to compare an absence against. This is the check activation runs as a corruption
  gate before trusting an epic's files.
- **`--scope story`** and **`--scope sprint`** check **completion of one node**: `status ==
  done`, all five `actual.*` metric fields present and correctly typed (numeric for
  `elapsed_hours`/`man_hours`/`hitl_hours`; `tokens_k`/`cost` may only be `N/A` under a
  non-Claude runtime), a structured `tokens_k.total` matching the sum of its four classes, and
  `cost` matching what those classes price out to under the node's own `model` field — a
  hand-edited cost cannot pass — and, for stories, `completion_evidence` present. A bare
  scalar `tokens_k` (the pre-rework shape) also fails under `--runtime claude` or
  `--require-tokens`: with no class split there is nothing to price `cost` against, so the
  cost check would otherwise be skipped entirely.

Activation depends on this distinction: it always runs `verify --scope epic` (structural),
never `--scope story`/`--scope sprint`, because activation is checking "is this file usable"
not "is this work finished."

## 8. Ordering is structural

Zero-padded names — `epic-{nnn}` (3 digits), `sprint-{nn}` (2 digits), story files
`E{nnn}-S{nn}-{nnn}.yaml` (3-digit sequence) — make lexical directory-listing order the
correct display and processing order. There is no separate ordering field to maintain and no
way for order to drift out of sync with intent, the way it could inside a YAML list.

## 9. Concurrency

Per-epic directories mean epic-scoped writes (status, estimate, actual, lock, move) touch
only that epic's own files — **no flock is needed for any of them.** Two developers working
different stories, different sprints, or different epics never contend for the same file.

`pm-calibration.yaml`, `issues.yaml`, and `adr-register.yaml` are the three shared-append
targets sharding does not shard, because all three are inherently cross-epic aggregates.
Every `set-actual` across every epic and every parallel subagent may append a calibration
sample to the first (`references/calibration-model.md`); every `append-issue` call across
every epic and every parallel subagent appends to the second, first allocating the item's key
from it (§3); every `adr-reserve` call across every parallel arch-gate agent allocates a block
of ADR numbers from the third (§1, §6). All three therefore run their **whole
read-modify-write cycle** — load, allocate/derive, mutate, save — inside one exclusive lock
each (`calibration_lock` / `issues_lock` / `adr_register_lock`), not just the save. Locking
only the save is not sufficient and was not safe: two concurrent callers each loaded the same
pre-write state and the second save silently dropped the first's item (for `issues.yaml`,
both a lost finding and, before key allocation existed, two callers computing the same next
number; for `adr-register.yaml`, two parallel agents both claiming the same ADR number), with
both calls still exiting 0. There is no `--flock` flag to remember for any of the three — the
lock is automatic, not opt-in. All three locks are re-entrant within a process, so a save
that nests inside its own lock (as `save_calibration` does) does not deadlock against its own
flock. Contrast this with per-epic node files (`epic.yaml`, `sprint.yaml`, story `.yaml`),
which need no flock at all because sharding gives each epic its own directory.

## 10. Read resolution at activation

Run once at startup, before any state read or write:

| Order | Found | Layout | Action |
|---|---|---|---|
| 1 | `{implementation_artifacts}/state/` | current | Proceed |
| 2 | `{project-root}/_bmad/state/` | legacy (per-epic file) | Block → `/l3io-util-doctor migrate-state` |
| 3 | `{implementation_artifacts}/sprint-status.yaml` | legacy (flat) | Block → same command |
| 4 | none | first run | Create lazily |

**Detection counts matches rather than stopping at the first hit.** If more than one layout
is present, block with a distinct error rather than silently preferring one — an interrupted
migration can leave two layouts populated at once, and guessing which is authoritative would
fork the project's state.

**Orphan check on apparent first-run.** Before creating anything under case 4, check whether
git tracks any `*/state/active/epic-*/epic.yaml` path that does not match the resolved
`{pm_state_root}`. If it does, halt instead of starting a blank project — this usually means
`implementation_artifacts` was repointed, not that the project has no history. A bounded
`find` covers the untracked case too.

**Gitignore verification.** Setup and activation both run `git check-ignore -q` on the
resolved state root and refuse to proceed silently if it is ignored, printing the negation
rule to add. Committing state is the entire point of this layout, so a state root that is
still gitignored is treated as a hard stop, not a warning.

### Bindings

| Binding | Resolves to |
|---|---|
| `{pm_state_root}` | `{implementation_artifacts}/state` |
| `{pm_issues_file}` | `{pm_state_root}/issues.yaml` |
| `{pm_calibration_file}` | `{pm_state_root}/pm-calibration.yaml` |

There are no other state-path bindings. In particular there is no per-status-folder or
per-node-kind path variable — every path below `{pm_state_root}` is resolved internally by
`pm-status.py` from keys, never bound by a step file.

## 11. Dependency fields

`depends_on` on an epic node (`epic.yaml`): list of epic keys that must be `status: done`
before this epic can start. Present regardless of which status folder the epic currently
sits in (most commonly populated while the epic is under `planned/`). Read by
`l3io-pm-plan` to build the execution graph.

`depends_on` on a story node: list of globally-unique story keys (`E{nnn}-S{nn}-{nnn}`) that
must be `status: done` before this story starts. Lives in that story's own file.

`l3io-pm-plan` validates all referenced keys exist and detects cycles before writing the
plan.
