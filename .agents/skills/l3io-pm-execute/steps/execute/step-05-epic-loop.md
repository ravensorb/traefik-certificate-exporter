# Step 05: Epic Loop

Communicate all responses in `{communication_language}`.

Execute each epic in `{execution_phases}` order. Within a parallel phase, dispatch epics concurrently
up to `{max_parallel_subagents}`. For each epic, promote it to active, claim the lock, dispatch sprint
subagents sequentially, then trigger epic closure.

## 0. Progress rendering — only where execution is serialized

This step dispatches epics **concurrently** inside a parallel phase. Several epic subagents each
printing a progress tree would interleave into unreadable output, and subagent stdout is buried
anyway — the contract there is a one-line `DONE — [metrics]`. So render only where exactly one
writer is producing output:

| Point | Render |
|---|---|
| Phase start, phase end (this step, top level) | Yes |
| Sprint boundary when the phase holds a single epic | Yes — see `step-04-sprint-closure.md` |
| Sprint boundary inside a parallel phase | No |
| Story boundary | Never |

Nothing is lost by suppressing. Every transition still lands in `{pm_state_root}/events.jsonl`,
so `report --watch 15` in a second terminal gives full-resolution live detail while the run's own
output stays legible. Say that once, at first phase start.

Bind `{progress_cmd}` to:

```bash
python3 {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format tree
```

Print its output verbatim wherever this file says to render. It is read-only and cannot affect
execution, so a non-zero exit from it is a reporting problem only: note it in one line and carry
on with the run. Never block execution on the progress view.

## 1. Phase iteration

For each phase in `{execution_phases}`:

**Render progress (phase start).** Run `{progress_cmd}` and print the output verbatim. On the
first phase of the run only, also print:

```
Live view during this run: python3 {pm_status} report --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml --watch 15
```

Bind `{single_epic_phase}` = `true` when this phase dispatches exactly one epic, else `false`.
Pass it into every sprint subagent's context block — `step-04-sprint-closure.md` reads it to
decide whether it may render.

If `parallel_flag=true` AND `len(epics) > 1`:
  Dispatch up to `{max_parallel_subagents}` epics concurrently (default 4, set per skill in
  `customize.toml`). Sprints within an epic are always sequential.
  Each epic runs §2–§6 below as an independent execution branch.

If `parallel_flag=false` OR single epic:
  Execute each epic sequentially.

After all epics in a phase complete, verify prerequisites for the next phase are all `status: done`
before starting it.

**Render progress (phase end).** Run `{progress_cmd}` and print the output verbatim, so the
phase's net effect is visible in one place before the next phase starts. This is the render that
matters most in a parallel phase: it is the first serialized point after concurrent epics have all
reported, and therefore the first time the whole phase can be shown coherently.

## 2. Skip completed epics, then promote to active (if needed)

**Check status before touching the epic** — this guard is mandatory and must run before
`move-epic`:

```bash
python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key}
```

If `status=done`, skip this epic entirely — do not move it, do not lock it, do not run
sprints or closure:

```
⏭️  {epic_key} is already done — skipping (listed in the plan, completed since).
```
Continue to the next epic in the phase.

This check is not an optimization. `move-epic` resolves an epic key in *any* status folder
and unconditionally rewrites `epic.yaml` status from the destination folder, so calling it on
a finished epic would drag the directory out of `archived/`, flip `done` back to
`in-progress`, and strand it in `active/`. A plan snapshot that predates the epic's
completion is the normal way to hit this, so the guard has to be here rather than left to
the plan being current.

Then promote:

```bash
python3 {pm_status} move-epic --state-root {pm_state_root} --epic {epic_key} --to active
```

`move-epic` moves the epic's whole directory (epic.yaml, every sprint.yaml, every story file)
from `planned/` to `active/` in one step and sets its status to `in-progress` — nothing to
create separately. If the epic is already under `active/` (resumed run), the same-location
move is a no-op, so this call is safe once the `done` case above has been excluded.

## 3. Claim ownership lock

```bash
python3 {pm_status} set-lock \
  --state-root {pm_state_root} \
  --epic {epic_key} \
  --session-id {session_id} \
  --ttl-minutes {epic_lock_ttl_minutes}
```

If this fails (another session holds the lock and TTL is live):
```
BLOCKED: {epic_key} lock held by another session. Skipping this epic.
```
Continue to next epic in phase.

## 4. Identify sprints to run

Reuse the roll-up already read in §2 — it lists each sprint under this epic with its
`status`, so there is no need to run `show` a second time:

```bash
python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key}
```

Find all sprints where `status != done` (sprint directories live at
`{pm_state_root}/active/epic-{epic_nnn}/sprint-*/`, in lexical — i.e. correct — order).
For sprint scope (`{exec_scope}=sprint`), filter to `{scope_sprint_key}` only.

Bind `{pending_sprints}` = ordered list of sprint `num` values (e.g. `["01", "02", "03"]`).

## 5. Sprint dispatch loop — three agent kinds, one story at a time

For each sprint in `{pending_sprints}` (always sequential — no parallel sprints within an
epic), run **5a, then 5b, then 5c, then 5d** before moving to the next sprint. 5d is part of
the per-sprint body, not a wrap-up: it spends the calibration 5c just produced on the sprints
still ahead, which only works if it runs between them.

### Why a sprint is not one agent

**Cost is the area under the context curve.** Every turn re-reads what the session already
holds, so a token entering at turn *t* is paid for again on each of the `T - t` turns after
it. Spend is the product of two axes — how many turns a session takes, and how much it is
carrying during them — never either alone:

```
cost = sum over turns of (tokens in context at that turn)
```

Reading early pulls the harder axis. The per-million figure and a worked example live in the
"What a read costs" section of `steps/shared/step-00-digest.md`, which you load on activation;
they are not repeated here.

**The turn axis is why a sprint splits.** Context grows as a session runs, so its area grows
with the square of its length: one 400-turn agent pays roughly twice what two 200-turn agents
pay for the same work, because splitting resets the growth. A sprint agent that ran story
prep, then every story, then every fix round, then closure was the longest-lived session in
the system and sat at the steepest part of that curve. So a sprint is dispatched as **prep,
then one agent per story, then closure** — each ending when its piece is done. Nothing is lost
by splitting: every hand-off here is already a file on disk.

Splitting is not free — each new agent re-pays the cold read of the baseline it needs — so it
wins exactly when the re-read saving beats the re-paid baseline. Keeping each agent's baseline
small is what holds that trade favourable, which is the volume axis again.

**What the corpus experiment did and did not show.** Deleting 4,415 lines from the project
moved the token composition not at all, and `cache_read` stayed 75–94% of every story. That
falsifies *repository size* as a driver — an agent never reads most of a repo. It says nothing
about the tokens an agent does load, and this file previously drew the wider conclusion that
volume is irrelevant. It is not: turn count alone does not even rank runs. One story measured
249 turns at $26.66 against a sibling's 82 turns at $49.55 — the short session was carrying
far more.

**Polling is the worst form of this, and it is the one that actually happened.** One story
measured 263 turns of which roughly 130 were one-line status polls, against ~62 turns of
real implementation — the same implementation count as two sibling stories that cost $4.44
and $5.52. Polling quadrupled it, and across a single run the habit was worth about $250.
That is why `{agent_contract}` carries a never-poll clause: a turn conveying one line of new
information costs exactly what a turn conveying a hundred does, because both re-read
everything before them.

### The orchestrator outlives every agent it dispatches

Every rule above governs a dispatched agent. You are not one — you run for the whole epic, so
your context is the longest-lived in the system and every token in it is re-read on every turn
you take for the rest of the run. The rules bind you harder, not less.

Concretely: read a subagent's **final line**, not its transcript. Do not re-read a story file
after prep has run — prep wrote what the dev needed into the document, and the document is the
hand-off. Do not accumulate findings in your own context; a phase that produces findings writes
them to disk and hands you the path. If you need a number, `pm-status.py show` and `report`
print it in a line, which is why they exist.

`{skip_phases}` was bound by `step-01-classify-work.md` §4 from the phase matrix there. Pass it
through unchanged to every dispatch — do not recompute it.

**Pass `{session_id}` down unchanged** to all three kinds. It is the orchestrator's, and every
subagent stamps its events and dispatch brackets with it. A subagent that generates its own
splits one run across two ids in `events.jsonl`, so the run can no longer be filtered out of
the log, and any `check-lock` from inside the sprint path sees the epic as owned by a stranger.

**Bracket every dispatch** with `dispatch --event open` before and `--event close` after,
same `--agent`/`--epic`/`--sprint`(/`--story`)/`--session-id` identity on both, closed on
**every** exit path — `DONE`, `BLOCKED` and `FAILED` alike, and before any branch, so an early
halt cannot skip it. A dispatch left open is not merely a missed close: the next dispatch that
opens the same identity silently overwrites it in `pm-status.py`'s pending map, and the
original hang's timestamp is lost. Per-story brackets are also what put each story's spend in
its own `actual` rather than the parent's `orchestration`
(`references/metrics-contract.md` §6).

### 5a. Prep the sprint

Compute `{story_keys}` = keys of all stories in this sprint with `status != done`.

```bash
python3 {pm_status} dispatch --state-root {pm_state_root} --event open \
  --agent l3io-pm-prep --epic {epic_key} --sprint {sprint_num} --session-id {session_id}
```

```
# l3io-pm execution context [AUTHORITATIVE — read before any step file]
work_type: {work_type}
skip_phases: {skip_phases}
max_fix_iterations: {max_fix_iterations}
epic_key: {epic_key}
epic_nnn: {epic_nnn}
sprint_root: {implementation_artifacts}/epic-{epic_nnn}/sprint-{sprint_nn}/
story_keys: [{story_keys}]
sprint_num: {sprint_num}
execute_skill_root: {skill-root}
single_epic_phase: {single_epic_phase}
headless: true

# Inherited activation — sections 1-7 of step-00-activate.md are ALREADY DONE for this
# project. Do not resolve config, self-install, detect layout, create directories, list
# epics, verify schema, or generate a session id. Use these bindings as given.
communication_language: {communication_language}
implementation_artifacts: {implementation_artifacts}
planning_artifacts: {planning_artifacts}
pm_status: {pm_status}
pm_state_root: {pm_state_root}
pm_issues_file: {pm_issues_file}
pm_calibration_file: {pm_calibration_file}
model: {model}
token_rates_json: {token_rates_json}
runtime: {runtime}
session_id: {session_id}

Load and execute in order:
  {skill-root}/steps/shared/step-00-digest.md
  {skill-root}/steps/sprint/step-02-story-prep.md

End with exactly one of:
  DONE — Stories prepared: N, estimates written: N
  BLOCKED: [one-line reason]
  FAILED: [one-line reason]
```

Close the bracket. On `BLOCKED`/`FAILED`, halt this sprint — the stories are not ready.

### 5b. One agent per story

Order `{story_keys}` so that any story's `depends_on` entries come before it, then dispatch
**one agent per story, sequentially**. Ordering here is what lets `step-03-dev-loop.md` treat
a dependency it cannot satisfy as `BLOCKED` rather than re-queueing: with one story per agent
there is no queue left to reorder.

For each `{story_key}` in that order:

```bash
python3 {pm_status} dispatch --state-root {pm_state_root} --event open \
  --agent l3io-pm-story --epic {epic_key} --sprint {sprint_num} --story {story_key} \
  --session-id {session_id}
```

```
# l3io-pm execution context [AUTHORITATIVE — read before any step file]
work_type: {work_type}
skip_phases: {skip_phases}
max_fix_iterations: {max_fix_iterations}
epic_key: {epic_key}
epic_nnn: {epic_nnn}
sprint_root: {implementation_artifacts}/epic-{epic_nnn}/sprint-{sprint_nn}/
story_keys: [{story_key}]
sprint_num: {sprint_num}
execute_skill_root: {skill-root}
single_epic_phase: {single_epic_phase}
headless: true

# Inherited activation — as in 5a. Do not re-run sections 1-7.
communication_language: {communication_language}
implementation_artifacts: {implementation_artifacts}
planning_artifacts: {planning_artifacts}
pm_status: {pm_status}
pm_state_root: {pm_state_root}
pm_issues_file: {pm_issues_file}
pm_calibration_file: {pm_calibration_file}
model: {model}
token_rates_json: {token_rates_json}
runtime: {runtime}
session_id: {session_id}

You are responsible for EXACTLY ONE story: {story_key}. Develop it, review it, run its
fix loop, write its completion evidence and actuals, and end. Do not start another story.

Load and execute in order:
  {skill-root}/steps/shared/step-00-digest.md
  {skill-root}/steps/sprint/step-03-dev-loop.md

End with exactly one of:
  DONE — Story: {story_key}, fix iterations: N, issues deferred: N
  BLOCKED: [one-line reason]
  FAILED: [one-line reason]
```

Close the bracket, then branch:
- `DONE` → continue to the next story
- `BLOCKED` → log it, stop dispatching stories in this sprint, and skip to 5c only if at
  least one story completed; otherwise halt the epic loop
- `FAILED` → log it and continue to the next story (one story failing is not the sprint
  failing); track the count

### 5c. Close the sprint

```bash
python3 {pm_status} dispatch --state-root {pm_state_root} --event open \
  --agent l3io-pm-closure --epic {epic_key} --sprint {sprint_num} --session-id {session_id}
```

Dispatch with the same context block as 5a, but `story_keys: [{story_keys}]` (the full sprint)
and:

```
Load and execute in order:
  {skill-root}/steps/shared/step-00-digest.md
  {skill-root}/steps/sprint/step-04-sprint-closure.md

End with exactly one of:
  DONE — Stories: N, Issues resolved: N, Issues deferred: N
  BLOCKED: [one-line reason]
  FAILED: [one-line reason]
```

Close the bracket, then branch:
- `DONE` → mark sprint done, then run 5d
- `BLOCKED` → log reason, halt epic loop, output: `BLOCKED: sprint {sprint_num} of {epic_key} — {reason}`
- `FAILED` → log reason, run 5d, then continue to next sprint (sprint failure is non-fatal at epic level); track count

### 5d. Re-estimate the sprints that have not run yet

**This runs once per sprint, inside the §5 loop — immediately after 5c reports `DONE` or
`FAILED`, and before you dispatch the next sprint's 5a.** `{sprint_num}` is the sprint that just closed.
It is not a post-loop step: run it after the last sprint too (it will find nothing left to
re-price and say so), but running it *only* then would price every remaining sprint from the
same prior that just missed, which is the whole defect this step exists to close.

**Do not update the calibration file here.** `set-actual` already derived and appended this
sprint's scope, fix and closure samples inline, at the moment each actual was written
(`references/metrics-contract.md` §8). An agent that "updates calibration" at this point
either no-ops or double-writes; there is nothing left to do and the earlier version of this
step said otherwise.

What is left to do is spend the calibration that was just learned. Re-estimate every story
that has not started, so the next sprint is priced with this sprint's evidence:

Bind `{reestimate_story_keys}` = every story under `{epic_key}` whose `status` is `backlog`
or `ready-for-dev`.

`show --epic` prints sprint rows only — it does not list stories. Per-story keys and statuses
come from the `--sprint` form, so collect them sprint by sprint. For each sprint in
`{pending_sprints}` whose number is greater than `{sprint_num}` — the sprints that have not
run yet — bind `{n}` to that sprint's number and run:

```bash
python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key} --sprint {n}
```

It prints one `{story_key} {status}` line per story in that sprint. Keep the keys whose status
is `backlog` or `ready-for-dev`, and union them across the sprints you visited.

Stories at `in-progress`, `review` or `done` are **excluded**: re-pricing work already under
way changes no decision and destroys the estimate the variance will be measured against.

If `{reestimate_story_keys}` is empty, 5d is finished — there is nothing downstream to
re-price. Continue the §5 loop with the next sprint (or fall through to §6 if this was the
last one).

Otherwise load `{skill-root}/steps/shared/step-estimate.md` with `{scope}={epic_key}` and
`{reestimate_story_keys}` bound. It re-runs `estimate-story` for exactly those keys —
`estimate-story` overwrites unconditionally, which is what re-estimation requires — and then
re-runs `estimate-rollup` for each affected sprint and for the epic, so the parents stay
equal to the sum of their children by construction.

Bind `{N}` = the number of keys in `{reestimate_story_keys}`.

**Report whether the calibration actually changed anything, because a silent nothing is the
signal worth catching:**

```
Re-estimated {N} unstarted stories after sprint {sprint_num}.
Calibration active: {active_components}
```

Bind `{active_components}` from:

```bash
python3 {pm_status} calibration show --state-root {pm_state_root}
```

It prints a `COMPONENT / BUCKET / SAMPLES / RATIO` table; a component is active where RATIO is
a number, and inactive rows read `(cold-start, needs 3)` instead. Name the active ones. If
none are active, report `none — still on the cold-start prior`, and treat that as the finding
it is: this sprint's closure produced no usable sample, so the next sprint is priced by the
same prior that just missed.

Do not report a before-and-after epic estimate. There is no scalar to report — an epic
estimate is five metrics, each a range, and no subcommand prints one.

## 6. Epic completion check

After all sprints in `{pending_sprints}` are processed:
- If any sprint is BLOCKED: output `BLOCKED: {epic_key} — sprint {sprint_num} blocked` and stop.
- If all sprints are `status: done`: proceed to step-06 (epic closure).

## 7. Output

```
Step 05 complete — epic: {epic_key}, sprints completed: {N}/{total}, stories done: {N}
```
