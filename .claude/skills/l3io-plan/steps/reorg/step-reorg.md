# Step Reorg: propose, confirm and apply a better plan shape

Communicate all responses in `{communication_language}`.

Loaded when the user invokes `/l3io-plan reorg`. This is the whole mode: it measures the
current plan, proposes one improvement, shows the user **the proposed plan** (not a list of
operations), and applies it only once they say yes.

---

## 1. What this mode may write, and what it may only read

**Writable: planned work.** Epics in the `planned/` bucket, their sprints and their stories.

**Read-only input: everything else.** Active work that has not completed, and archived work,
are read so that ordering and dependency satisfaction are correct — an epic in flight still
constrains what can be scheduled against it. They are **never written**. `pm-status.py
reparent-story` refuses a story outside `planned/` outright (exit 2), because a story that has
started carries actuals, calibration samples and `events.jsonl` history keyed to its current
key, none of which a re-parent moves. Do not try to work around that refusal; it is the scope
rule, not an obstacle.

Say both halves out loud in the report. A user who sees a proposal that does not mention their
in-flight epic should be able to tell the difference between "it was considered and left alone"
and "it was not looked at".

**Three things this mode never does**, stated here because each is a plausible-looking next
step and all three are wrong:

- It does not add, split, or invent work. It moves, reorders and retires what is already there.
- It does not edit a story's title, estimate, `depends_on` or content. The proposal format has
  nowhere to put any of them (§3).
- It does not delete anything, ever. Retirement archives. Deletion happens only if the user
  asks for it in so many words, and this mode is not where that happens.

## 2. Preflight

`{pm_state_root}`, `{implementation_artifacts}`, `{pm_status}`, `{model}` and
`{token_rates_json}` are already bound by `steps/shared/step-00-activate.md`. Bind one more,
from the config already resolved there (`references/config-resolution.md` §3):

- `{reorg_auto_apply}` — `modules.l3io-pm.reorg_auto_apply`, default `never`.

An absent `modules.l3io-pm` section is normal and means `never`. It is never a reason to run
setup.

Then confirm there is something to reorganise:

```bash
uv run {pm_status} list-epics --state-root {pm_state_root} --format json
```

If no epic sits in `planned/`, stop here:

```
Nothing to reorganise — no epics are in planned/. Reorg writes planned work only; active and
archived epics are read-only input.
DONE — reorg: no planned work
```

Create a working directory for this run's artifacts. These are inputs to the tooling and to
the journal, not deliverables; they are plain files under the planning artifact tree, never
under the state tree:

```bash
mkdir -p {planning_artifacts}/reorg
```

Bind `{reorg_run}` = `{planning_artifacts}/reorg/{timestamp}` (ISO-8601 UTC, colons removed),
and use it as the prefix for every file below.

## 3. Stage 1 — measure the plan you have

One read verb hands you the shape of the plan; the analyzer measures it. Neither touches the
state tree, and neither decides anything.

```bash
uv run {pm_status} dump-plan --state-root {pm_state_root} > {reorg_run}-current.json
uv run {skill-root}/scripts/plan-graph.py analyze < {reorg_run}-current.json > {reorg_run}-findings.json
```

Read `{reorg_run}-findings.json`. Every finding carries an `id`, a `severity`, the `nodes`
involved, a **measured** value and what that value `suggests`. The findings are the evidence
your rationale argues from (§7). They are re-derivable: anyone can re-run those two commands
and get the same numbers, which is the entire reason the rationale cites them instead of
asserting that some stories "belong together".

Two findings change what you do next rather than merely informing it:

- **`cycle` or `dangling-dependency` (severity `blocker`).** The plan cannot be ordered at all.
  A reorg can break a cycle by re-grouping, and that is a legitimate proposal — but say so
  first, because the user's plan is broken right now and they may not know.
- **`isolated-story` (severity `question`).** Nothing depends on it and it depends on nothing.
  This is **a question, never a retirement recommendation.** Leaf work is very often the actual
  deliverable of a plan. If you mention it at all, mention it as a question for the user.

The `cross-epic-coupling` and `unbacked-cross-epic-dependency` findings are the objective
(§7). Record their edge counts — those are the "was" numbers the report compares against. Also
record the `dependency-chain` finding's `hops`: it is context, not a target, because no move a
reorg can make shortens it.

## 4. Stage 2 — write a target placement

**You propose where things belong. You never propose operations, and you never choose a key.**
The tooling diffs your target against the current tree and derives the operations itself, and
the allocator decides every new key.

Write `{reorg_run}-target.yaml`:

```yaml
target:
  - key: E007-S02-004        # the node's CURRENT key
    epic: E003               # where it belongs
    sprint: S01              # sprint within that epic; may not exist yet
    order: 5                 # relative order among the stories THIS target moves
  - key: E007-S02-005
    epic: E007
    sprint: S02
    order: 1                 # unchanged rows are allowed, and are a no-op
retire:
  - key: E041
    reason: "nothing depends on it; its spec anchor was removed in docs/adr/0008"
```

Four rules the format enforces, each of which will refuse the whole target if broken:

1. **`key` is the node's current key.** There is no field for a destination key. Keys are the
   allocator's business.
2. **The target is total.** Every planned story appears exactly once, in `target` or inside a
   retired epic. An omission is an error, never an implied "leave it alone" — an agent that
   forgot a node and an agent that meant to leave it look identical from the outside, and the
   second is far more common. An unchanged story is one line with its current placement.
3. **Placement and ordering are the only expressible things.** No titles, no estimates, no
   `depends_on`, no new keys. Any other field is a refusal, not a warning. This is the whole
   safety argument for letting an agent write a target: drift is not mitigated here, it is
   unrepresentable.
4. **`retire` is epic-level and needs a reason.** `planned/`, `active/` and `archived/` are
   folders of epic directories, so there is nowhere to put a single retired story. A
   retirement with no reason leaves nobody able to judge later whether it should come back.

**What `order` can and cannot do.** It sequences the stories *this target moves*, and the
allocator realises that sequence as key order. It **cannot reorder a story that stays put** —
the only way to do that is to re-key it, churning its key, its document filename, its
`previous_keys` and its remote-issue mapping for a purely local sequencing change. Do not
promise the user more than this in the report. It is also not a loss worth working around:
within-sprint order is local sequencing, while the objective (§7) is the number of
dependencies crossing an epic boundary, which reordering inside a sprint cannot change.

Propose **one** improvement with its evidence, and stop. This mode is not trying to produce
the optimal arrangement; it is trying to produce one a user can check in about a minute.

## 5. Stage 3 — validate, before anything is shown or written

```bash
uv run {skill-root}/scripts/reorg-validate.py --target {reorg_run}-target.yaml \
  --stage {reorg_stage} < {reorg_run}-current.json
```

`{reorg_stage}` is `structure` on the first pass and `balance` on the second (§11). Under
`balance` the validator additionally refuses any row that changes a story's **epic**, which is
what stops the balancing pass undoing the structural one — see §11 for why that is a refusal
rather than an instruction.

Exit 0 means the target is legal. Exit 2 means it is refused **whole**, and every offending row
is named on stderr so one pass fixes them all. A partly-applied target is neither the old plan
nor the new one, and the rationale a user accepts describes the whole thing.

On exit 2: fix the target and re-run. Do not show the user a refused target, and never hand a
refused target to the derivation. If three attempts do not produce a valid target, stop:

```
BLOCKED: could not produce a valid reorg target — <the validator's last message>
```

## 6. Stage 4 — measure the plan you are proposing

The report compares two plans, so measure the second one with the **same instrument** that
measured the first. Build a preview of the proposed tree and run the analyzer over it again.

Build `{reorg_run}-proposed.json` from `{reorg_run}-current.json` and the target by:

- moving each story object **verbatim** into the sprint list its target row names, creating a
  sprint entry where the target names one that does not exist yet;
- dropping every epic named in `retire` (its stories go with it);
- leaving `active` and `archived` exactly as they are.

**No field of any node may be edited while doing this.** If a field differs between the two
files other than by a story having moved between sprint lists, that is a bug in the preview,
not a proposal — fix it rather than reporting it.

```bash
uv run {skill-root}/scripts/plan-graph.py analyze < {reorg_run}-proposed.json > {reorg_run}-proposed-findings.json
```

You now have the same measurements for both shapes: `critical_path_hours`,
`cross_epic_edges`, `planned_epics`, `planned_stories`, and the blocker count.

**Phases** for the proposed shape are computed exactly as `steps/plan/step-05-dependency-graph.md`
computes them: a topological sort over epic `depends_on`, with a phase marked parallel only
when its epics do not depend on one another. A target cannot edit `depends_on`, so the epic
graph changes only by losing the retired epics.

**Effort numbers in the report are a projection, and must be labelled as one.** They are the
same per-story estimates re-aggregated under the proposed grouping — a reorg does not change
how big a story is. They are not a roll-up: `sprint.estimate` and `epic.estimate` are defined
as the sum of their children *plus* calibrated closure and orchestration bands, so a sprint
this proposal creates or empties shifts those bands. The authoritative numbers are written by
`estimate-rollup` after the apply (§10), and may differ slightly from the projection. Say so
in one line rather than letting the user discover it.

## 7. Stage 5 — the report

**The report is the proposed plan, rendered the way plans already are.** It is not a changelog
of moves. "Are these four moves right?" makes the user reason about operations; "is this a good
plan?" is the question they actually have, and the one they are equipped to answer in a minute.

Use the summary shape `steps/plan/step-06-plan-output.md` §5 prints after every normal plan
run, so no new reading skill is required and the two are directly comparable side by side.
Changed items carry a `(was …)` annotation inline, so a reader sees a plan first and notices
what moved second.

```
📋 Reorg proposal — {retire_count} retirement(s), {move_count} stories re-placed

Scope: {epic_count} epics across {phase_count} phases     (was {old_epic_count} epics across {old_phase_count} phases)

Phase 1 (parallel): {epic_keys} — est. {time_low}–{time_high} hrs wall-clock, {cost_low}–{cost_high} cost
Phase 2 (sequential): {epic_keys} — est. {time_low}–{time_high} hrs wall-clock, {cost_low}–{cost_high} cost

Critical path: {critical_path_str} ({total_time_low}–{total_time_high} hrs)     (was {old_low}–{old_high})

Readiness: {readiness}

Total effort (guardrail): {man_hours} man-hrs, {tokens_k}k tokens, {cost}     (was {old_man_hours}, {old_tokens_k}k, {old_cost})
Cross-epic dependencies: {cross_epic_edges}     (was {old_cross_epic_edges})
Effort figures are projected from the current story estimates; roll-ups are rewritten after apply.

WHY
  {one short paragraph per group of moves, each citing a measured finding}

MOVES
  {plain-language list: what moves, and what stays}

Keys change. A moved story is re-keyed — E007-S02-004 becomes E003-S01-005 — because the key
encodes the epic and sprint. The old key is kept in the story's previous_keys, so GitHub issue
mappings reconcile on the next /l3io-sync. If you have an old key written down somewhere, that
is the one it becomes.

Nothing is deleted. A retired epic is moved to archived/ with the reason recorded, and undo
brings it back. Undo restores where work sits, not the numbers: an undone story returns to the
sprint it came from with a new key, because a vacated key is never reissued.

Accept this plan? (y / n / moves-only)
```

### 7.1 The objective, and the things that are reported but never pursued

**Primary objective: reduce the cost of discovering a problem late** — concretely, **minimise
the dependencies that cross an epic boundary**. Each crossing edge is a serialisation point
between units that would otherwise be independent, and it is the one thing a re-placement can
remove: move a story into the epic its dependencies live in and the edge is gone. That is the
number the report leads with and the one a proposal is argued on (ADR-0011).

**Report these; never aim at them.** Each is a real property of the plan that **no move this
mode can make will change**, so presenting one as a target would promise an outcome the move
set cannot deliver:

- **Dependency chain** (in hops) — a reorg never edits `depends_on`, so no regrouping shortens
  it. Say how serialised the work is; do not claim to reduce it.
- **Sprint balance** — a reorg never makes work smaller. This is the balancing pass's input.
- **Closure overhead** — the only way a reorg moves effort at all, and second-order: fewer,
  fuller sprints pay fewer closure bands.

**Effort is an impact, not a goal, and not a guardrail either** — a guardrail no legal move can
breach is not a guardrail. Show any effort change the regrouping causes, and name it as a
consequence rather than defending it as a trade. Treating effort reduction as the goal would
make retirement — deleting scope — the highest-scoring move available, which is precisely the
wrong incentive to give this mode.

Four guardrails are reported when they change, each with the "was" beside it: cross-epic
coupling (dependency edges crossing an epic boundary), sprint cohesion (overlap of `Spec:`
anchors cited within a sprint), sprint balance (spread of sprint `elapsed_hours` within an
epic), and total effort across all five metrics. **A proposal that regresses any of them needs
a stated reason in `WHY`.**

### 7.2 What `WHY` must contain

One short paragraph per group of moves. Each one cites a **measured** signal from
`{reorg_run}-findings.json` and names the change it produces. Checkable:

```
E007-S02 blocked three epics and held one story that did not belong to it:
E007-S02-004 cites only auth.md#token-refresh, which E003's stories also cite.
→ 3 cross-epic dependencies removed; sprint anchor overlap 0.0 → 0.8
```

Not checkable, and not acceptable: "these belong together", "this is cleaner", "better
separation of concerns". If a reason cannot be re-derived from the findings file, either find
the finding that supports it or drop the move.

A retirement paragraph additionally states what was checked: that nothing depends on it, what
it resolves (or does not), and why it is no longer needed.

### 7.3 What `MOVES` must contain

Plain terms, both halves. What moves, and what stays:

```
Moves:  E007-S02-004 → E003 sprint 01 (re-keyed)
        E012-S01-002, E012-S01-003 → E012 sprint 02 (re-keyed within their epic)
Stays:  everything else in E007 and E012; all of E001, E002, E003's existing stories
Retires: E041 "Legacy export shim" → archived/, recoverable
Untouched: E019 and E022 are active and were read for ordering only, never written
```

A story that moves between sprints of the **same** epic is still re-keyed — the key encodes
both — so it belongs in this list, not in "stays".

## 8. Confirmation

`{reorg_auto_apply}` decides whether the prompt is shown. It never decides whether the reorg
is **recorded**: pre-authorisation skips the question, not the journal.

| `{reorg_auto_apply}` | Reparenting | Retirement |
|---|---|---|
| `never` (default) | ask | ask |
| `moves` | apply without asking | ask |
| `always` | apply without asking | apply without asking |

Any other value: treat it as `never` and say so once — a misspelled setting must not silently
become a broader authorisation than the user wrote.

All interaction is conversational. There is no flag for any of this, and none of these answers
is a command-line argument.

- **y** — apply the whole proposal.
- **n** — apply nothing. Say so plainly and stop; rejecting is free and costs the user nothing.
  Print the status line in §13 with `declined`.
- **moves-only** — apply the reparenting and skip every retirement. Rewrite the target with
  `retire:` emptied and **re-run §5** before deriving: a target with retirements removed is a
  different target, and the one that was validated is not the one you would be applying. The
  stories inside a kept epic must then appear in `target` — re-run §4 for them.

Under `moves`, still print the proposal and still ask about the retirements; only the
reparenting question is skipped.

## 9. Stage 6 — derive and apply

Derive the operation list. You do not write it; the derivation computes it by diffing, which
removes a whole class of error outright — a malformed or self-contradictory operation list
cannot exist if nobody writes one.

```bash
uv run {skill-root}/scripts/reorg-derive.py --target {reorg_run}-target.yaml \
  < {reorg_run}-current.json > {reorg_run}-operations.json
```

**Capture the pre-state hash before the first write.** The journal needs it, and it cannot be
recovered afterwards:

```bash
uv run {pm_status} reorg-log --state-root {pm_state_root} --hash
```

Keep that digest as `{pre_hash}`. Also keep `{reorg_run}-current.json` — together with
`{reorg_run}-target.yaml` it is what re-diffing needs if the apply is interrupted.

Apply the operations **in the order the derivation emitted them**. The order is the point of
that file, not a formatting choice:

1. `create-sprint` — every destination that does not exist yet, before anything moves into it.
   `reparent-story` refuses a missing destination by design.

   ```bash
   uv run {pm_status} import-node --state-root {pm_state_root} \
     --epic {epic} --sprint {sprint} --status backlog --title "{title}"
   ```

   `import-node` is idempotent by skip, so re-running after a partial apply is safe.

2. `reparent-story` — grouped by destination and sequenced by the target's `order`, so the
   allocator hands out keys in the sequence the proposal showed.

   ```bash
   uv run {pm_status} reparent-story --state-root {pm_state_root} \
     --artifacts-root {implementation_artifacts} \
     --story {story} --to-epic {to_epic} --to-sprint {to_sprint}
   ```

   It prints `OK reparent-story {old_key} -> {new_key}`. **Record every old → new pair** — the
   report in §12 needs it, and so does the journal. Both trees move together under one lock:
   the state node and the story document, with the document's frontmatter `key:` rewritten and
   its optional `-slug` filename suffix preserved.

3. `retire-epic` — last, so anything leaving a retiring epic has already left.

   ```bash
   uv run {pm_status} retire-epic --state-root {pm_state_root} \
     --epic {epic} --reason "{reason}"
   ```

   This is a `git mv` to `archived/` with `retired_reason` and `retired_at` recorded. It never
   deletes.

**If an operation fails, stop at that operation.** Do not continue, and do not try to undo by
hand. Re-running the derivation against the same target reports exactly the operations still
outstanding, because it compares states rather than replaying a script — that property is why a
half-finished reorg is detectable instead of silent. Report what landed, name the failing
operation, and say that re-running `/l3io-plan reorg` with the same target resumes it.

## 10. Stage 7 — record and re-estimate

**Record the reorg in the journal.** A reorg that is not recorded cannot be undone. Record it
**after** the apply: the journal stamps the post-apply hash at record time, and that is the
hash undo's guard compares against.

Assemble `{reorg_run}-record.yaml` with three top-level keys:

```yaml
rationale: |
  {the WHY and MOVES blocks exactly as the user saw them}
pre_hash: "{pre_hash}"          # from `reorg-log --hash`, captured before the first write
operations:
  - op: create-sprint
    epic: E003
    sprint: S01
  - op: reparent-story
    story: E007-S02-004         # the key it had
    new_key: E003-S01-005       # what reparent-story printed
    from_epic: E007
    from_sprint: S02
    to_epic: E003
    to_sprint: S01
  - op: retire-epic
    epic: E041
    reason: "{the reason given}"
    from_status: planned
```

These are the derived operations from `{reorg_run}-operations.json` with the three fields the
derivation cannot know added: `new_key` from what each `reparent-story` printed, `from_epic`
and `from_sprint` split out of its `from` pair, and `from_status` on each retirement. The
journal refuses a record missing any of them, and refuses an operation of a kind it cannot
invert — an entry that looks undoable and is not would be worse than no entry at all.

`rationale` must be the proposal the user accepted, **verbatim**. It is what they will be shown
when they come back to undo it, and a summary written from memory is not the thing they agreed
to.

```bash
uv run {pm_status} reorg-log --state-root {pm_state_root} --record {reorg_run}-record.yaml
```

It prints `OK reorg-log recorded R0001`. Quote that id in the report — it is what the user
names when they ask to undo.

**Re-estimate what the moves changed.** Story estimates are unchanged by a reorg, but sprint
and epic roll-ups are defined as the sum of their children plus closure and orchestration
bands, so every sprint and epic that gained or lost a story is now stale:

```bash
uv run {pm_status} estimate-rollup --state-root {pm_state_root} \
  --epic {epic} --sprint {sprint} --model {model}
uv run {pm_status} estimate-rollup --state-root {pm_state_root} \
  --epic {epic} --model {model}
```

Add `--token-rates '{token_rates_json}'` to both when `{token_rates_json}` is non-empty — the
same override the rest of this skill passes, so the reorg does not price its roll-ups against a
different rate card than the plan did.

**A plan snapshot is not rewritten.** Snapshots are immutable once written and
`l3io-execute` may be reading one. Tell the user to run `/l3io-plan` for a snapshot that
reflects the new shape, exactly as `/l3io-plan estimate` does.

## 10.1 Report the epic dependencies this reorg made unnecessary

**A reorg cannot finish its own job, and this is where it says so.** Its objective is to
remove dependencies crossing an epic boundary — but it never edits epic-level `depends_on`,
because the target format has no field for one. So after the last story edge between two epics
is gone, `E001 depends_on E003` is still declared, phases are built from that declaration, and
the two epics keep running in sequence. The parallelism the whole proposal was for does not
arrive until somebody drops the edge.

Compare the `unneeded-epic-dependency` findings in §6's measurement of the proposed plan
against §3's measurement of the plan you started with. Report only the ones **this reorg
caused** — present now, absent before. A declaration that was already unjustified before the
reorg is not this run's business and is noise here.

For each, print the two commands, filled in:

```bash
uv run {pm_status} set-depends-on --state-root {pm_state_root} --epic {epic} --remove {target}
```

Then `/l3io-plan`, to rebuild the snapshot so execution picks up the new order.

```
↯ This reorg removed the last {n} story dependency(ies) justifying {epic} depends_on {target}.
  Dropping it would let {epic} and {target} run in the same parallel phase.
  Optional — the dependency may be a sequencing decision no story edge expresses.
```

**Say "optional" and mean it.** "Ship the API before the client" is a real ordering with zero
story edges behind it, and nothing measured here can tell that from a leftover. Offer the
command; do not run it as part of the reorg, and do not treat declining as an unfinished step.

`set-depends-on --remove` refuses on its own if a story edge still crosses — so a stale
measurement cannot cause a wrong removal. `--force` exists for the sequencing case.

**If more epics end up sharing a phase, say so once.** Epics in one parallel phase are
dispatched concurrently into a single working tree, and nothing checks that their source files
are independent. That is a known limit worth naming at the moment parallelism increases,
rather than at the moment two concurrent epics collide.

## 11. Stage B — balance sprint load, inside the structure you just built

Run this **after** §10 has recorded the structural pass, and only then. Bind `{reorg_stage}` =
`balance` and run §3 through §10 a second time, with the differences below. Everything else —
the target format, the validator, the derivation, the apply loop — is unchanged, because
balancing is the same operation against a narrower move set.

### 11.1 Skip it unless there is something to balance

Two conditions, both checked before anything is proposed:

1. **The plan carries estimates.** `sprint-imbalance` is measured from `elapsed_hours`; with
   none recorded there is nothing to level and nothing to level it against. Say so and stop:

   ```
   Balancing skipped — no story estimates recorded yet, so sprint load cannot be compared.
   Run /l3io-plan to estimate, then ask for a reorg again if you want the sprints levelled.
   ```

2. **The analyzer reports at least one `sprint-imbalance` finding.** No finding, no proposal —
   do not invent a rebalance because the stage exists.

Either way this is a **normal, silent-ish outcome**, never a failure. The structural pass has
already been applied and recorded; a skipped Stage B changes nothing about that.

### 11.2 The move set is narrower, and the validator enforces it

A balancing target may move a story **between sprints of the same epic**. It may not:

- change a story's **epic** — `reorg-validate.py --stage balance` refuses the row
- **retire** anything — retirement is a structural decision, refused under this stage
- violate any dependency, which the ordinary ordering rules already prevent: a dependency must
  sit in an earlier sprint of the epic, or the same sprint at a lower `order`

**Why a refusal and not an instruction.** The structural pass spends its entire proposal moving
stories to remove dependencies that cross an epic boundary. A balancing pass free to move them
back could undo that while legitimately levelling load, and the result would pass every other
check, because both placements are individually legal. Making the epic change unrepresentable
means the composition cannot regress what the first pass achieved — the same argument the
target format makes everywhere else (§5.3.1): drift is not mitigated, it is impossible.

### 11.3 The report says what it is

Use the §7 report shape, with the objective line replaced — this pass is not claiming to change
structure:

```
⚖ Balance proposal — {move_count} stories re-placed within {epic_count} epic(s)

{epic}: S01 {old}→{new} hrs · S02 {old}→{new} hrs · S03 {old}→{new} hrs   (ratio {old_ratio} → {new_ratio})

WHY
  {one paragraph per epic, citing its sprint-imbalance finding}

MOVES
  {what moves between which sprints, and what stays}

Cross-epic edges: unchanged — a balancing pass cannot move work between epics.
Total effort: unchanged except for closure overhead, if the number of sprints changed.
```

State the unchanged lines explicitly. A reader who has just accepted a structural proposal needs
to know this pass is not quietly revisiting it.

### 11.4 One journal entry, not two

Record **both** passes in a single `reorg-log` entry (§10), with the structural operations first
and the balancing operations after, in the order they were applied. Undo then reverses the whole
reorg as one act, which is what a user who says "undo that reorg" means — they are not thinking
in stages, and an undo that reverted only the balancing half would leave a tree matching neither
the plan they had nor the one they accepted.

The `rationale` holds both reports, verbatim, in order.

## 12. Output

```
✅ Reorg applied — {move_count} stories re-placed, {retire_count} retired

Re-keyed:
  E007-S02-004 → E003-S01-005
  ...

Journal entry: {reorg_id}
Undo: ask for it in plain language — "undo that reorg" — and name the entry if there is more
than one. There is no flag.

Next: run /l3io-plan to write a plan snapshot that reflects the new shape, and /l3io-sync to
reconcile the re-keyed stories with their issues.
```

If the user declined, print instead:

```
No changes made — the proposal was declined. Nothing in planned/ was written.
```

## 13. Output status line

```
Step reorg complete — moved: {move_count}, retired: {retire_count}, journal: {reorg_id}
DONE — Reorg: {move_count} moved, {retire_count} retired, cross-epic edges {old_edges} → {new_edges}
```

Use `DONE — Reorg: declined` when the user said no, and `BLOCKED: <one-line reason>` when §5
or §9 stopped the run.
