# l3io-pm state and metrics digest

Loaded on its own, without the activation procedure around it, because who needs it and who
needs that procedure are different sets. A dispatched subagent inherits an already-bootstrapped
project — config resolved, `pm-status.py` installed, layout detected, directories made, schema
verified — and re-running any of it changes nothing while costing 8,633 B and six subprocesses
per dispatch. It still needs every rule below, on every invocation. So the orchestrator loads
`step-00-activate.md` (which ends by loading this file) and a subagent loads only this.

Keep this in context for the whole invocation.

This is everything a normal run needs from the state and metrics contracts. **Do not load
`references/status-files.md`, `references/metrics-contract.md`, or
`references/calibration-model.md` unless the routing table at the end of this section sends
you there** — re-reading them per subagent is the single largest avoidable token cost in the
system.

**Precedence.** `pm-status.py` is the authority: it enforces every rule below mechanically, so
if its behavior and this digest disagree, the script is right. Then the full reference. This
digest is last — treat it as stale if it conflicts.

### Keys

- Epic `E{nnn}` → directory `epic-{nnn}` · Sprint `S{nn}` → `sprint-{nn}`
- Story `E{nnn}-S{nn}-{nnn}` → file `E{nnn}-S{nn}-{nnn}.yaml` in that sprint's directory
- Backlog item `BL-E{nnn}-{nnn}` (`BL-E000-{nnn}` for repo-global)
- Zero-padded always. Node fields use `key:`, never `id:`.

### You have no inbox

No message will ever arrive. Nothing you send can be answered. Every hand-off in
this system is a file on disk — that is the context boundary, and it has no
exception for "just one quick question".

If you need a decision you cannot make yourself:

1. Write what you know, and what you need decided, to the node or the closure
   artifact.
2. End your turn with `BLOCKED: <one-line reason>`.

Waiting is never correct and is never cheap: a blocked wait outlives the prompt
cache, and the next turn re-creates the entire context prefix at full price.

### Never poll — arm one background wait and stop

When something runs outside your turn — a background command, a long build, a task you
dispatched — **arm a single wait for it and end your turn.** Do not loop, do not re-check,
do not "just confirm it's still running". If you cannot arm a wait, end with `BLOCKED`
naming what you were waiting for.

**Every poll is a full turn, and a turn costs your whole history, not one line.** Cost is
turns × what you carry through them. Read narrowly, end early. See
`steps/execute/step-05-epic-loop.md` §5.

**These rules reach a spawned subagent only if you put them there** — a `bmad-*` agent
loads none of this file. Bind `{agent_contract}` to the lines below and include them
verbatim in **every** spawn prompt you issue:

```
- You have no inbox. No reply will arrive. If you need a decision you cannot make,
  write it to disk and end with `BLOCKED: <one-line reason>`. Never wait.
- Never end a turn on a question. Asking and stopping is worse than waiting: the
  work is abandoned rather than recorded. Decide it yourself and write down what
  you assumed, or end with `BLOCKED:` — those are the only two exits.
- Never poll. If something runs outside your turn, arm ONE background wait and stop.
  Every poll is a full turn and a turn re-reads your entire history — a one-line
  "still running?" costs what the whole conversation costs.
- Once you have written your final line you are done. Do not arm a wait, schedule a
  wake-up, or start anything that can call you back: each wake is a fresh turn that
  re-reads everything, finds nothing to do, and can arm another.
- Every token you read is re-read on every later turn, so what you load costs
  turns × its size. Read what the task names; widen only with a reason.
- Your final line must be exactly one of `DONE — [brief metrics]`,
  `BLOCKED: [one-line reason]`, or `FAILED: [one-line reason]`.
```

### Never build a state path by hand for a write

`pm-status.py` is the only component that resolves a key to a location for writes. Address
nodes by key when writing; if you find yourself concatenating `state/active/epic-...` to write
a file, stop and use a subcommand. Direct reads are fine where a step file directs one — e.g.
`steps/sprint/step-02-story-prep.md` reads `epic.yaml` directly for `goal`, a field `show`
does not print.

Uses `{pm_status}` (bound in §2).

### The calls a sprint or epic run makes

```
set-status    --state-root S  (--story KEY | --epic ID [--sprint ID])  --status S
              [--title T] [--flock] [--no-events] [--session-id ID]
set-actual    --state-root S  --node {story,sprint,epic}  (--story KEY | --epic ID [--sprint ID])
              [--block {actual,orchestration}]   (orchestration: sprint/epic only, never story)
              [--elapsed-hours H] [--man-hours H] [--hitl-hours H]
              [--tokens-input K] [--tokens-output K] [--tokens-cache-write K] [--tokens-cache-read K]
              (any --tokens-* requires --model M; --cost rejected, exit 2 — see the
              HARD RULE below for the all-four-classes and derived-cost rules)
              [--tokens-na]   (runtime=other only; forbidden under runtime=claude)
              [--runtime {claude,other}] [--flock] [--no-calibrate]
set-estimate  --state-root S  (--story KEY | --epic ID [--sprint ID])
              story: --man-hours H --hitl-hours H --elapsed-hours H --tokens-k K
              sprint/epic: --man-hours-low/-high, --hitl-hours-low/-high,
                           --elapsed-hours-low/-high, --tokens-k-min/-max
              (--time-hours* = deprecated alias for --elapsed-hours*;
              --cost* rejected, exit 2 — use estimate-story/estimate-rollup)
              [--confidence {low,medium,high}] [--flock]
set-field     --state-root S  (--story KEY | --epic ID [--sprint ID])  --field NAME --value V
              (refuses completion_evidence.tests_passing, exit 2 — use add-test-run)
add-test-run  --state-root S  --story KEY  --command CMD  --exit-code N
              (record every run, failures too; tests_passing derives from the LAST
              run of each distinct command)
sync-story-doc --artifacts-root A  --story KEY  --status S
              (mirrors status into the story doc's frontmatter; a missing or
              frontmatter-less doc warns and returns 0 — never roll state back)
adr-reserve   --state-root S  --epic ID  --slug SLUG  [--count N]
              (N sequential ADR numbers under a lock, before dispatch; one per line)
estimate-story   --state-root S  --story KEY  --classification {simple,standard,complex}
                 [--model ID] [--token-rates JSON]
estimate-rollup  --state-root S  --epic ID  [--sprint ID]  [--model ID] [--token-rates JSON]
verify        --state-root S  --scope {story,sprint,epic}  (--story KEY | --epic ID [--sprint ID])
              [--require-tokens] [--runtime {claude,other}] [--token-rates JSON]
show          --state-root S  --epic ID  [--sprint ID]
report        --state-root S  [--plan P] [--format tree|json|md] [--out F] [--all] [--watch SECS]
              [--stall-minutes N]
dispatch      --state-root S  --event {open,close}  --agent NAME
              [--epic ID] [--sprint ID] [--story KEY] [--session-id ID]
set-lock      --state-root S  --epic ID  --session-id SESS  [--ttl-minutes N]
clear-lock    --state-root S  --epic ID
check-lock    --state-root S  --epic ID  --session-id SESS
move-epic     --state-root S  --epic ID  --to {planned,active,archived}
archive-epic  --state-root S  --epic ID  (alias for move-epic --to archived)
append-issue  --file F [--key K]  --epic {nnn}  [--sprint S]  --title T  --source S
              --severity {Low,Medium,High,Critical}  [--description D] [--allow-duplicate]
rates         [--model ID] [--token-rates JSON]   (read-only; the effective rate table)
usage         [TRANSCRIPT...] [--claude-session ID] [--model ID]   (read-only. NO ARGUMENT =
              this session's transcript; verifies identity, exits 2 rather than guess. Prints
              per-class tokens + --tokens-* flags. NEVER hand-sum usage fields.)
```

Exit codes: `0` ok · `2` usage error · `3` not found · `4` verification failure · `5` epic
locked elsewhere. Branch on these rather than parsing stdout.

`set-status` and `set-actual` append to `state/events.jsonl` automatically — you never write
that file, and never pass a flag to make it happen.

### Estimates and actuals — the HARD RULE

Every planning point and every closeout, at story, sprint, and epic level, records **both** an
`estimate` and an `actual` for all five metrics, in canonical order: `elapsed_hours` (AI
wall-clock), `man_hours` (counterfactual — what a developer would have taken by hand, assessed
at closure from the delivered diff/tests/scope, never observed), `hitl_hours` (human attention
actually spent supervising — observable), `tokens_k` (a mapping of `total` plus the four token
classes), and `cost`. This is enforced at write time, not advisory.

**`cost` is derived, never entered** — computed once from `tokens_k × the model's rate table`
and frozen; `--cost*` exits 2 on every runtime. Fix the token counts or
`modules.l3io-pm.token_rates`, never the cost field.

Under `--runtime claude`, token actuals are read **exactly** from the session transcript's
`usage` fields, split by class, passed with `--model`, and `set-actual`/`verify` **reject**
`N/A` for tokens. All four classes are required together: a partial set exits 2, and a bare
scalar `tokens_k` on an actual fails `verify` (there is no class split to price `cost`
against). Pass an explicit `0` for a class that really is zero. Under any other runtime,
capture what is exposed or pass `--tokens-na` and record `N/A` — **never a guess**.
`man_hours` and `hitl_hours` have no `N/A` path on any runtime.

`set-actual` derives the calibration sample itself. Write
`completion_evidence.fix_iterations` **before** calling it, or the scope-versus-fix split
cannot see it.

### What a read costs

A token you read is re-read on every turn you take afterwards. At the ~80 turns a story agent
runs, content loaded near the start costs about **$25 per million tokens**, not the $0.50 the
cache-read rate suggests. A 2,000-line file read to find one contract is real money, and four
agents each reading it is four times that.

So: read the files the task names. If you need something it did not name, name it to yourself
first — "which file, and what am I looking for" — then read that file, not its directory. If
what you need turns out not to be in what you were given, that is a defect in the hand-off
worth reporting in your final line, not a reason to widen the read for the rest of the run.

### When you do need the deep contract

| If you need to… | Read |
|---|---|
| diagnose a structural `verify --scope epic` failure | `references/status-files.md` §7 (Addressing — see "`verify` — two different checks behind one subcommand") |
| understand what `verify` enforces for a story or sprint | `references/metrics-contract.md` §5 (Enforcement — what is actually checked, and where) |
| know which fields a node carries | `references/status-files.md` §4 (Per-file schema) |
| handle a migration or legacy layout | `references/status-files.md` §10 (Read resolution at activation) |
| declare or read `depends_on` | `references/status-files.md` §11 (Dependency fields) |
| resolve an epic lock question | `references/status-files.md` §6 (Ownership lock) |
| capture token/cost actuals correctly | run `{pm_status} usage` — never hand-sum; `references/metrics-contract.md` §3 |
| write an estimate or actual by hand | `references/metrics-contract.md` §4 (Writing estimates and actuals) |
| apply the estimation roll-up, fix-reserve, or orchestration-band model | `references/metrics-contract.md` §6 (The estimation roll-up) and §7 (The fix reserve) |
| explain a calibration result, or run the one-time metrics migration | `references/calibration-model.md` (whole file — do not go via `metrics-contract.md`) |
| record the orchestrator's own overhead, or the token rate table | `references/metrics-contract.md` §3 and §6 |
| see a full worked example | `references/metrics-contract.md` §10 (Worked example) |
