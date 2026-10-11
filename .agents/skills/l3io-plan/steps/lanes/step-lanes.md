# Lanes — who owns what, and how several developers share one plan

Communicate all responses in `{communication_language}`.

**A lane is a slot in a partition, never a person.** Who works a lane lives in each
developer's own gitignored config, so a name never reaches the repository. That is also why a
lane is a **number**: `backend` and `sarah` are the same shape, so no pattern could permit one
and refuse the other.

## 1. Is this project running lanes at all?

Read `{lane_count}` (`modules.l3io-pm.lane_count`, set by `/l3io-setup`).

- **Absent, or `1`** — lanes are off. Say so in one line and stop:
  `Lanes are off for this project (one developer). /l3io-setup can change that.`
  **Do not prompt, do not propose, do not assign.** An absent module config section is a
  valid permanent state, never a first-run trigger, and a project that never asked for lanes
  must not be able to tell this mode exists.
- **`N > 1`** — continue.

The mode is a **configured answer**, never inferred from the tree. A project set up for three
lanes that has not assigned any yet looks exactly like a single-developer project if you only
scan epics, and the two must not get the same answer.

## 2. Has the partition been made?

```bash
uv run {pm_status} dump-plan --state-root {pm_state_root} \
  | uv run {skill-root}/scripts/plan-graph.py analyze
```

If **no planned epic carries a `lane`**, there is a partition to propose — go to §3. If some
do, go to §4; an existing partition is a decision already taken, and this mode does not
re-open it.

## 3. Propose a partition

```bash
uv run {pm_status} dump-plan --state-root {pm_state_root} \
  | uv run {skill-root}/scripts/plan-graph.py partition --lanes {lane_count}
```

Report **both** numbers it returns, because they are different objectives and a good score on
one can hide a bad score on the other:

- **`cross_lane_edges`** — how much the lanes still wait on each other. Zero means genuinely
  independent work.
- **`idle_phases` per lane** — a partition can be perfect by connectivity and still hand one
  lane only late-phase epics, leaving that developer idle until another finishes.

```
📋 Proposed partition — {lane_count} lanes over {n} epics

Lane 1: E001, E002, E003, E004   phases 1–3
Lane 2: E005, E006               phases 1–2   idle in phase 3
Lane 3: E007, E008               phases 2–3   idle in phase 1

Cross-lane dependencies: 2   (E005 → E007, E006 → E008)
```

**If the proposal carries crossings or idle phases, say what fewer lanes would cost.** Asking
for more lanes than the work supports forces splits through real dependencies — the price is
real and belongs in front of the person deciding whether to add a developer, not behind them.

**Confirm before assigning.** On agreement, write each epic's lane:

```bash
uv run {pm_status} set-field --state-root {pm_state_root} --epic {epic} --field lane --value {lane}
```

`set-field` refuses anything that is not a lane number, and refuses `lane` on a sprint or
story: **one epic is one lane**, and children inherit it from the directory they live in.

## 4. Show a lane's view

A **filter** over the current plan, not a second document — a per-lane file would be another
source of truth and would go stale the next time the plan is rebuilt.

With `{lane}` bound (from the developer's own gitignored config), show that lane. Without it,
show every lane.

```
📋 Lane 2 — 3 epics across phases 1–3

Phase 1 (parallel): E005, E006 — est. {low}–{high} hrs
Phase 3 (sequential): E008 — est. {low}–{high} hrs

Waits for:    nothing
Waited on by: Lane 1 (E004 depends on E006)
Idle in:      phase 2 — no epic owned
ADR block:    0014–0019 (reserved)
```

`Waits for` and `Waited on by` come from the `cross-lane-dependency` findings in §2.

Rendering this to a file is fine, but the rendering **names the snapshot it came from**, so a
printed copy cannot be mistaken for current once the plan is rebuilt.

## 5. The protocol — what makes this safe

**Every `flock` in `pm-status.py` guards one filesystem, and two clones share none.** State is
committed to git, so between developers, concurrency is mediated by `git merge` and nothing
else. The protocol exists because of that, and all of it follows from it.

**Commit and push before execution begins.** Everyone forks from one commit. This does not
eliminate the merge; it bounds it to a known surface.

**Each lane writes only its own epic directories.** `state/{status}/epic-{nnn}/` holds
everything for an epic, so disjoint ownership means git has nothing to reconcile — measured:
two lanes working two epics produced **no conflict at all** in the state tree.

**Four files are shared, and they are not equally hard:**

| File | Behaviour |
|---|---|
| `state/events.jsonl` | Both lanes append. `merge=union` is literally the right semantics — measured: 2 lines + 2 lines = 4, all identities preserved. **This project needs the rule added; see below** |
| `state/pm-calibration.yaml` | Order-independent samples. A lost one degrades estimates without corrupting state |
| `state/issues.yaml` | `next:` is **per-epic**, so disjoint owners never collide semantically |
| `state/adr-register.yaml` | A **global** allocator — the one real collision |

### The one line this project must add

**The extension does not ship a `.gitattributes` into your repository, and cannot** — that file
belongs to your project, not to an installed skill. Without the rule, **every** multi-developer
merge conflicts on `state/events.jsonl` alone, and the conflict looks alarming while being
entirely mechanical.

Check whether it is already there, and offer to add it if not:

```bash
grep -q 'events.jsonl' .gitattributes 2>/dev/null && echo present || echo missing
```

The line to add — `union` is built into git and needs nothing installed:

```
**/state/events.jsonl merge=union
```

Ask before writing it: it is the user's file. Then write it yourself rather than handing them
the editing — once they have agreed, locating the file and appending a line is mechanical work
there is no reason to give back. Append; never rewrite a `.gitattributes` that already exists.

**Reserve ADR blocks before the fork**, which is why the allocator's inability to cross clones
stops mattering — a reservation made before anyone diverges needs no lock:

```bash
uv run {pm_status} adr-reserve --state-root {pm_state_root} --epic {epic} --slug {slug} --count 6
```

## 6. What lanes do NOT solve

**Source-file collisions.** The dependency graph proves two epics have no `depends_on` between
them. It says **nothing** about whether both rewrite the same module. Two lanes can be
perfectly independent in the plan and still spend a week diverging on one file — the failure
that makes teams abandon parallel work, and the one invisible to every signal here.

Say this out loud when proposing a partition. Lanes partition *work*, not *code*.

## 7. Output status line

```
Step lanes complete — lane_count: {lane_count}, assigned: {n} epic(s), cross-lane edges: {n}
```
