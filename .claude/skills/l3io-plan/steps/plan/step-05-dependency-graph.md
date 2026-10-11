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

### 1.1 A story dependency that crosses epics must be backed by the epic graph

**Existing is not the same as scheduled.** The checks above ask only whether a story key
resolves. Phases, built in §3, come from **epic-level** `depends_on` — so a story dependency
crossing `E001 → E003` with no `E001 depends_on E003` behind it leaves both epics with no
edge between them, lands them in the **same parallel phase**, and runs them concurrently while
one needs the other finished.

For each story-level `depends_on` whose target sits in a different epic, check that the
depending story's epic declares that epic in its own `depends_on`. Report each one that does
not:

```
⚠️  {n} story dependency(ies) cross an epic boundary the epic graph does not know about:
      E001-S01-001 → E003-S01-001   (E001 does not declare depends_on: [E003])
    Phases come from epic-level dependencies, so these epics can be scheduled to run
    concurrently. Add the epic-level dependency, or move the story.
```

**Report, never halt.** A hand-written story dependency produces this with no reorg involved,
so existing projects are likely to carry one; halting would block a plan run on a defect the
user did not cause. The message names the one line of YAML that fixes it. This is expected to
become an error in a later release once projects are clean — until then it must not change
`{readiness}` or stop the run.

**Do not auto-derive the epic dependency.** Inferring `E001 depends_on E003` from the story
edge would silently rewrite the declared graph, and a story dependency that was itself wrong
would become a wrong phase plan with no trace of where it came from.

`/l3io-plan reorg` reports the same thing as `unbacked-cross-epic-dependency`, from the same
rule, so the two agree by construction.

## 2. Detect cycles, and 3. group epics into phases — one command

Both answers come from the same graph, so they come from the same call. It reads `dump-plan`
on stdin, writes nothing, and takes no lock:

```bash
uv run {pm_status} dump-plan --state-root {pm_state_root} \
  | uv run {skill-root}/scripts/plan-graph.py phases
```

**Do not compute this by hand.** This used to describe a depth-first cycle search and Kahn's
algorithm in prose, for you to run in your head over the whole epic set, on every plan run.
It is the computation that decides what runs **concurrently** — the one thing in this step an
execution run acts on directly — which makes it the worst possible candidate for being done
from memory.

### On a cycle

The command returns `phases: []` with an `error` naming the cycle. A cyclic graph has no
topological order at all, so there is nothing to emit; set `{cycle_detected}` = true and halt:

```
🔴 Dependency cycle detected — the epic graph has no execution order.
BLOCKED: dependency graph has errors — resolve before continuing.
```

Run `plan-graph.py analyze` for the cycles themselves: it reports **every** simple cycle, not
the first one found, so a plan with two broken clusters is fixed in one pass rather than
surfacing one, being fixed, and failing again.

Halt here for an invalid reference from §1 as well.

### Otherwise

Bind `{phases}` to the command's `phases` array, `{phase_count}` to `phase_count`. The shape:

```yaml
phases:
  - phase: 1
    parallel: true
    epics: ["E001", "E002"]
    dependencies: []
  - phase: 2
    parallel: false
    epics: ["E003"]
    dependencies: ["E001", "E002"]
```

**`parallel` is `len(epics) > 1`, and nothing else.** One epic cannot run concurrently with
itself. (`l3io-execute`'s epic loop guards on `parallel_flag=true AND len(epics) > 1`
independently, so this flag has never been able to cause a concurrent dispatch of a single
epic on its own.)

`dependencies` lists what the phase waited for — the union of its epics' `depends_on` within
the planned set. A dependency on active or archived work does not order a phase: those epics
are read-only context and have no phase of their own.

Pass `{phases}` to `step-06-plan-output.md`, which writes it into the plan snapshot. That
snapshot is what `l3io-execute` reads; it never recomputes the order.

## 4. Identify the longest dependency chain (structural)

**This step does not compute the weighted critical path, and must not try.** `step-estimate`
runs *after* this one, so the epic estimates a weighted path needs do not exist here on a first
plan, and on a re-plan they are the previous generation's — about to be overwritten two steps
later. This section used to read `estimate.elapsed_hours_high` from state and fall back to "all
epics in phase order, no differentiation" when it found nothing, which is what every first plan
got: a headline critical path that was just the epic list. The weighted path is computed in
`step-06-plan-output.md` §5, from the per-phase estimate blocks that step builds **after**
estimates are written.

What *is* computable here, because it needs no estimates, is the structural one: the longest
chain of `depends_on` edges. It is the ordering constraint the graph imposes no matter what
anything costs.

Walk the dependency edges and record the longest path by **edge count**:

Record as `{longest_chain_epics}` = the epics on that chain, in dependency order. A graph with
no edges at all has no chain — record an empty list and say so rather than listing every epic,
which would imply an ordering constraint that does not exist.

## 5. Report graph

```
Dependency graph:

Phase 1 (parallel — {count} epics):
  • E001 "Auth Layer" — no dependencies
  • E002 "API Gateway" — no dependencies

Phase 2 (parallel — {count} epics):
  • E003 "Mobile App" — depends on: E001 ✅, E002 ✅

Longest dependency chain: E001 → E003  (3 epics)
```

No hours on this line. Estimates are written two steps later, so any duration printed here
would either be the previous generation's or invented — and the two `estimated_hours_*` tokens
this line used to carry were never bound anywhere, so it printed the token text verbatim.

## 6. Check the plan's shape — here, before anything is estimated

**This is the earliest point the check can run, and the earliest is where it belongs.** Every
finding a reorg can act on is structural — it needs `depends_on` and nothing else — so the
shape of the plan is fully knowable now, three steps before `step-estimate` and four before a
snapshot is written. Reporting it later would mean telling a user their grouping is wrong only
after they have paid to estimate it and generate a snapshot of the shape they are about to
change.

Read-only; writes nothing and takes no lock:

```bash
uv run {pm_status} dump-plan --state-root {pm_state_root} \
  | uv run {skill-root}/scripts/plan-graph.py analyze
```

Bind `{shape_advisory}` from the `findings` array, by **severity**, in this order:

1. Any finding of severity `blocker` (`cycle`, `dangling-dependency`) → §2 above has already
   halted on these. Nothing further to say here.
2. Otherwise, any finding of severity `warn` (`cross-epic-coupling`,
   `unbacked-cross-epic-dependency`) →
   `↻ This plan's shape could be improved: {the measured reason, from each finding's "measured" and "suggests"}. Run /l3io-plan reorg to see a proposal.`
3. Otherwise → bind the empty string and print nothing.

**Only `warn` triggers the suggestion, and those two findings are the two things a reorg can
act on.** Moving a story into the epic its dependencies live in removes a crossing edge; nothing
else here is movable. `dependency-chain` and `isolated-story` are `info` and `question`
precisely because no move changes them — a reorg never edits `depends_on` — and they fire on
perfectly healthy plans, so advising on them would print the suggestion after every planning
round. A suggestion that always appears is one people learn to skip past.

**`sprint-imbalance` is not checked here**, and that is not an oversight: it needs
`elapsed_hours`, which `step-estimate` has not written yet. It is checked in
`step-06-plan-output.md` §5.1, where the numbers exist.

Say the measured reason, never a bare recommendation. "3 dependency edges cross E007↔E003" is
checkable by the person reading it; "this plan could be better organised" is not, and a reader
who cannot check it has to either trust it or ignore it.

If the analyzer fails or is absent, bind the empty string and carry on — a missing advisory must
never fail a plan run that otherwise succeeded.

Print `{shape_advisory}` after the graph report above, omitting the line entirely when empty.

## 7. Output status line

```
Step 05 complete — phases: {phase_count}, epics in graph: {in_scope_epic_count}, longest chain: {longest_chain_epics joined by " → "}
```
