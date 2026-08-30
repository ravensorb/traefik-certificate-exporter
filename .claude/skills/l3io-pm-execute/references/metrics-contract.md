# Metrics Contract (estimates & actuals)

Communicate all responses in `{communication_language}`.

This file is the single source of truth for **which** numbers l3io-pm records, **what they
are called on disk**, **how they are captured**, **where they are enforced**, and **how
estimates learn from them**. It is a **deep reference, consulted on demand** — do not load it
at activation. `steps/shared/step-00-digest.md` carries the HARD RULE and the runtime
capture rule, plus a routing table naming the section to read for each case that needs this
file: token/cost capture detail (§3), writing an estimate or actual by hand (§4), explaining a
calibration result (§8), or a worked example (§10).

Most of what follows is now mechanized. §6 (roll-up), §7 (fix reserve), and §8 (calibration)
describe what `estimate-story`, `estimate-rollup`, and `set-actual` do themselves — read them
to understand or debug a number, not to perform a calculation by hand.

This file outranks the digest. Where they disagree, this file is correct — and `pm-status.py`
outranks both.

`status-files.md` owns *where state lives*. This file owns *what the numbers in it mean*.

Where this document and `CLAUDE.md` disagree, **this document follows the code**
(`pm-status.py`) and says so explicitly in §9. Anything described here as "specified, not
mechanized" is agent discipline only — no script checks it.

---

## 1. The HARD RULE

**Every planning point and every closeout — at story, sprint, and epic level — records both
an `estimate` block and an `actual` block, and each block covers all five metrics.**

A story, sprint, or epic does not sign off with an estimate block missing, an actual block
missing, or any individual metric missing from either.

Why it exists: estimation only improves if plan-vs-actual is captured at the same
granularity every time. A single skipped closeout does not just lose one data point — it
silently biases every calibration ratio derived from that component, and the bias is
invisible afterwards because there is no record that the sample was ever due. The rule is
therefore absolute rather than best-effort, and it is checked mechanically at write time
and again at read-back (§5).

**Retrospective level.** `CLAUDE.md` states the rule at "story, sprint, epic, and
retrospective" level. There is no retrospective *node* — retrospective data is written onto
the sprint or epic node as `retrospective.summary`, `retrospective.velocity`,
`retrospective.carry_over`, `retrospective.learnings` via `set-field`, and it carries no
metric fields of its own. The retrospective's numbers **are** its sprint's or epic's
`estimate`/`actual` blocks. Do not invent a separate metric block under `retrospective.`.

## 2. The five metrics

`METRIC_FIELDS` in `pm-status.py` is exactly `("elapsed_hours", "man_hours", "hitl_hours",
"tokens_k", "cost")`, in that order. That order is canonical wherever the five are listed.

| Metric | Meaning | Unit | Observable? |
|---|---|---|---|
| `elapsed_hours` | AI wall-clock time from dispatch to completion | hours (decimal) | Yes |
| `man_hours` | **Counterfactual** — what a developer, working without AI assistance, would have needed to deliver this work | hours (decimal) | **No — re-assessed at closure, not observed** |
| `hitl_hours` | Human attention actually spent supervising the run | hours (decimal) | Yes |
| `tokens_k` | Total tokens consumed — a **mapping**, not a scalar (see below) | thousands (K) | Yes (Claude); N/A elsewhere |
| `cost` | Billed cost for those tokens | USD (decimal) | **No — derived, never entered** |

**`man_hours` is counterfactual, not an observation of the run.** It answers "how long would
a human developer have taken to build exactly what this diff, these tests, and this scope
delivered?" — assessed by reviewing the delivered work itself, at closure. It is **not** a
self-report of how long the dev/review subagents ran (that is `elapsed_hours`), and it is
**not** derived by any formula from the other metrics. **Anti-anchoring requirement:** form
this number **before** reading the node's own `estimate.man_hours` (or any report that shows
it) — reading the estimate first anchors the re-assessment toward it. This requirement is
agent discipline, "specified, not mechanized" (§9) — no script enforces the read order. The
closure step files (`steps/sprint/step-04-sprint-closure.md`, `steps/execute/step-06-epic-closure.md`)
place the re-assessment as their first step for exactly this reason.

**`hitl_hours` is new and observable.** It is the human's own supervisory attention — reading
output, approving a gate, redirecting a stuck run — not the AI's wall-clock time and not a
developer counterfactual. Cold-start bands (per `BASE_BANDS`, §6): simple 0.1–0.3, standard
0.2–0.5, complex 0.3–1.0.

**`elapsed_hours` is the only wall-clock name.** There used to be a differently-spelled
wall-clock key on the estimate side (a "time hours" name) and `elapsed_hours` on the actual
side — two names for the same metric, needing a translation table (`ESTIMATE_TO_ACTUAL`)
everywhere the two were compared. That table is gone: estimate and actual now use the **same
field name**, `elapsed_hours`, at every level. The old estimate-side flags survive on
`set-estimate` only as **deprecated CLI aliases** (`--time-hours`/`--time-hours-low`/
`--time-hours-high`) that write the `elapsed_hours*` keys — the old key name does not appear
on disk anywhere, in a freshly-written node.

**`tokens_k` is a mapping, not a scalar**, wherever it is written by the mechanized paths
(`estimate-story`, `estimate-rollup`, `set-actual`):

```yaml
tokens_k:
  total: 320          # what is banded, calibrated, and priced
  input: 48
  output: 16
  cache_write: 96
  cache_read: 160
```

`total` is stored, not recomputed on read, so a node stays self-describing to anything that
does not know the class list — but it is always the class sum, and `verify` checks that (§5).
The **total** is what activates scope/closure/orchestration calibration and what a report
shows by default; the **class split** exists only to price `cost` and to make an input/output
or cache-hit-rate mix shift visible. `TOKEN_CLASSES` is `("input", "output", "cache_write",
"cache_read")`, in that order.

**`cost` is derived, never entered.** `cost = Σ(class tokens × that class's per-model rate) /
1000`, computed once at capture time (inside `set-actual`, `estimate-story`, or
`estimate-rollup`) and frozen on the node alongside the `model` field that priced it.
`set-actual` and `set-estimate` **reject** `--cost`/`--cost-low`/`--cost-high` outright — exit
`2` — with a message pointing at the token counts or `modules.l3io-pm.token_rates` instead.
`verify` recomputes `cost` from the stored `tokens_k` and `model` and fails if they disagree by
more than $0.005 (§5) — a hand-edited `cost` cannot survive `verify`.

**Rate table.** `TOKEN_RATES` in `pm-status.py` is a per-model, per-class USD-per-million-token
table (Anthropic first-party rates). It is overridable via `modules.l3io-pm.token_rates`
(merged in, not replaced — an override for one model does not blank the rest) and reaches the
CLI as `--token-rates '<json>'` on `set-actual`, `set-estimate`* , `estimate-story`,
`estimate-rollup`, `verify`, and `rates`. An unknown model is a hard error (`KeyError`, exit
`2`) — never a silent default; a silently-wrong rate is exactly the failure this model exists
to remove. `--model` is **required** whenever any `--tokens-*` flag is given: the same token
count prices roughly 2× apart between, e.g., a $3/M and a $10/M-input tier, so there is no
safe default to fall back to. `pm-status.py rates [--model ID] [--token-rates JSON]` prints
the effective table (read-only) so the value actually in force — including any override — is
inspectable without reading source or guessing.

**Both reach the CLI from activation bindings, not from the CLI's own defaults.**
`step-00-activate.md` §1 binds `{model}` from `modules.l3io-pm.default_model` (default
`claude-opus-5`) and `{token_rates_json}` from `modules.l3io-pm.token_rates` (JSON-encoded;
empty when the key is absent). Every step file that estimates or writes an actual passes
`--model {model}`, and adds `--token-rates '{token_rates_json}'` only when that binding is
non-empty. `DEFAULT_ESTIMATE_MODEL` inside `pm-status.py` is the fallback for a direct CLI
call, not the project's answer: without the binding every estimate in a project prices at
`claude-opus-5` whatever it actually runs on. And an override passed to the writers but not
to `verify` fails **every** node, because `verify` re-derives `cost` against whatever rate
table is in force for it. Full contract: `references/config-resolution.md` §3.

*(`set-estimate` accepts `--token-rates` too, but only to reject `--cost*` with a clear usage
error, per the point above — it never derives a cost itself; only `estimate-story`/
`estimate-rollup` do.)*

### Field names on disk

Because estimate and actual now share field names, the schema is closer to symmetric than it
used to be — but two divergences remain and matter:

```yaml
# story node — estimate is single values
estimate:
  man_hours: 6
  hitl_hours: 0.8
  elapsed_hours: 1.5
  tokens_k: {total: 320, input: 48, output: 16, cache_write: 96, cache_read: 160}
  cost: 1.32                # derived by estimate-story from tokens_k x rates; never entered
  model: claude-opus-5
  confidence: high           # low | medium | high
  fix_factor: 1.25           # the fix multiplier applied (one per classification)
  scope_ratios:               # the scope ratio applied, PER CALIBRATED METRIC — load-bearing
    man_hours: 1.1            #   (see §8: the sample divides these back out)
    hitl_hours: 1.0
    elapsed_hours: 1.0
    tokens_k: 1.0

# sprint and epic nodes — estimate is low/high ranges
estimate:
  man_hours_low: 12
  man_hours_high: 18
  hitl_hours_low: 1.5
  hitl_hours_high: 2.5
  elapsed_hours_low: 2.5
  elapsed_hours_high: 4
  tokens_k_min: 600
  tokens_k_max: 950
  cost_low: 2.48              # derived by estimate-rollup from tokens_k_min/max x rates
  cost_high: 3.93             #   (600K/950K split by the cold-start mix, priced at `model` below)
  model: claude-opus-5
  closure_ratios:              # the closure ratio applied, PER CALIBRATED METRIC — load-bearing
    man_hours: 1.14            #   (see §8; 1.0 means the cold-start band applied)
    hitl_hours: 1.0
    elapsed_hours: 1.0
    tokens_k: 1.0
  orchestration_ratios:        # the orchestration FRACTION applied, per calibrated metric
    man_hours: 0               #   (0 while unseeded — see §6, §8)
    hitl_hours: 0.09
    elapsed_hours: 0.11
    tokens_k: 0
  confidence: high

# actual — identical shape at story, sprint, and epic level; always single values
actual:
  elapsed_hours: 3.2
  man_hours: 15               # counterfactual re-assessment at closure — NOT observed
  hitl_hours: 1.8
  tokens_k: {total: 812, input: 122, output: 41, cache_write: 244, cache_read: 405}
  cost: 2.02                  # derived; written by the tool, never by hand
  model: claude-sonnet-5

# sprint/epic only — the orchestrator's own overhead, a SEPARATE block from `actual`
orchestration:
  elapsed_hours: 0.6
  man_hours: 0                # AI-only overhead; no human-developer counterfactual
  hitl_hours: 0.1
  tokens_k: {total: 90, input: 14, output: 5, cache_write: 27, cache_read: 44}
  cost: 0.23
  model: claude-sonnet-5

# stamped by set-actual once the node's calibration sample has been emitted;
# a later set-actual on the same block records nothing (§8, Idempotency)
calibration_sampled_at: '2026-08-16T22:34:03Z'
orchestration_sampled_at: '2026-08-16T22:41:10Z'   # separate marker for the orchestration block
```

**Divergence 1 — `tokens_k`'s shape depends on which command wrote it.** The mechanized paths
(`estimate-story`, `estimate-rollup`, `set-actual`) always write the full mapping above. The
**manual** `set-estimate` path writes `tokens_k` (story) / `tokens_k_min`/`tokens_k_max`
(sprint, epic) as a **plain scalar** — it has no per-class flags, so there is nothing to build
a mapping from. Every reader that needs a metric's numeric value — `_estimate_metric`,
`_actual_metric` — checks for the mapping shape first (`hasattr(v, "get")`) and falls back to
treating a bare scalar as the total, so both shapes read correctly; but a story estimated by
hand through `set-estimate` will show a scalar `tokens_k` next to a mechanized sibling's
mapping. Prefer `estimate-story`/`estimate-rollup` for anything that should carry a class
split. On the **actual** side the scalar shape is not merely inferior, it **fails**
`verify --runtime claude` (§5): with no class split there is nothing to price `cost` against,
so the cost invariant cannot run.

**Divergence 2 — `cost`'s on-disk type depends on which path wrote it, not on which
subcommand.** `set-actual` writes an **unquoted float** in the normal, token-given path —
`cost_from_tokens` returns a `float`, and `cmd_set_actual`'s write loop only routes *string*
values through `_coerce` (`block_data[k] = v if not isinstance(v, str) else _coerce(k, v)`), so
a float is stored as-is: `cost: 0.11`, no quotes. The **only** case `set-actual` writes `cost`
as a string is the `--tokens-na` sentinel path, where `cost` is set to the literal string
`"N/A"` (never a real value) — that string is what actually reaches `_coerce`, and `_is_na`
returns it unchanged.

| Writer | Path | `cost` is written as |
|---|---|---|
| `set-actual` | tokens given (the normal case) | an **unquoted float** (`cost_from_tokens`'s return value, stored directly) |
| `set-actual` | `--tokens-na` (runtime=other only) | the literal **string** `"N/A"` |
| `estimate-story` | — | a **float** (`round(value, 2)`) |
| `estimate-rollup` | — | a **float** (`round(value, 2)`) |

So in ordinary operation — any node with a real `cost` — every writer agrees on an unquoted
float; the only quoted form is the `N/A` sentinel itself, which is a string by definition
regardless of which field carries it.

Every reader goes through `_num_or_none`, which parses both a bare number and a numeric
string and strips a leading `$`, so a hand-constructed quoted numeric string (e.g. from an
older hand-edit or a backfill script) reads correctly everywhere — on the calibration and
roll-up paths, and in `_accumulate_actuals` (what `show` and `report` sum), which routes
through `_actual_metric`/`_num_or_none` like the rest. There is no longer a reader that does
a bare `float()` and silently drops a `$`-prefixed value.

Even so: pass a **bare decimal with no currency symbol** if you are ever constructing one by
hand for a test or a backfill — `1.32`, never `'$1.32'`. `verify` compares `cost` against
what `tokens_k` prices out to, and a currency-prefixed figure is a hand-edit by definition.
Currency symbols belong in prose reports, never in the state files. In normal operation this
never arises: `cost` is derived, not typed in.

`tokens_k.total` (and each class) is stored as an int when the value is integral, otherwise a
float. `elapsed_hours`, `man_hours`, and `hitl_hours` are floats.

## 3. Runtime detection and capture

Two runtimes are recognized: `claude` and `other`. Every metric-writing call takes
`--runtime {claude,other}`, and it **defaults to `other`** — the permissive value. Bind
`{runtime}` at activation and pass it explicitly on every `set-actual` and `verify` call;
relying on the default silently disables the strict path.

### Under `--runtime claude`

`elapsed_hours`, `man_hours`, and `hitl_hours` are always real numbers — no runtime has an
`N/A` path for these three. Tokens are captured **exactly**: sum `input_tokens`,
`output_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` from the session
transcript's `usage` fields, convert to thousands, and pass them as
`--tokens-input`/`--tokens-output`/`--tokens-cache-write`/`--tokens-cache-read` along with
`--model`. All four are required together (§5); pass an explicit `0` for a class that really
is zero. `set-actual` derives `tokens_k` (the mapping) and `cost` from them — never pass
`--cost`; it is rejected.

**Which messages count toward which node is §6's Attribution rule, not a per-metric
judgement.** The rule "scope it to the messages belonging to the node being closed" used to
live here; it is the defect the orchestration term exists to remove, because orchestrator
messages belong to no node under it and their spend therefore entered no sample at all. Read
§6 for the three buckets and the `dispatch_open`/`dispatch_close` boundary that separates
them.

`N/A` (via `--tokens-na`) is **forbidden** for tokens here — `set-actual` exits `2` if
`--tokens-na` is combined with `--runtime claude`. This is the mechanical enforcement point of
the HARD RULE (§5).

### Under `--runtime other`

Capture whatever the runtime exposes. If tokens are genuinely not observable (e.g. Copilot),
pass `--tokens-na`, which records both `tokens_k` and `cost` as the literal string `N/A`.
`--tokens-na` cannot be combined with any explicit `--tokens-*` count — pick one or the other.

**Never estimate, extrapolate, or back-calculate a token or cost actual.** A guessed actual
is worse than a missing one: `N/A` is skipped by calibration, whereas a guess is
indistinguishable from a measurement and permanently corrupts the learned ratio. `man_hours`
and `hitl_hours` are always observable/assessable and must always be real numbers, on every
runtime — there is no `N/A` for either, ever.

Values treated as `N/A` by `_is_na`: `N/A`, `NA`, `NONE`, and the empty string, in any
case, after stripping. An **absent** field is not the same as `N/A` — absence fails
`verify`, an explicit `N/A` passes it under `--runtime other`.


### Do not read the usage fields by hand — run `usage`

```bash
# a story's own spend — the window comes from its dispatch bracket
python3 {pm_status} usage --state-root {pm_state_root} --story {story_key} --model {model}

# a sprint's, an epic's, or an explicit window
python3 {pm_status} usage --state-root {pm_state_root} --epic {epic_key} --sprint {sprint_num} ...
python3 {pm_status} usage --since ISO --until ISO ...
```

**Identity is not scope, and both are required.** Verifying that a transcript is yours says
nothing about which part of it belongs to the node being closed. A session transcript spans
everything that session ever did — one observed file covered a whole epic lineage and its bare
total was ~66× the sprint actually being closed. Recording that as a node's actual would poison
calibration for the rest of the epic, and it would look plausible doing it.

So the window comes from the node's own `dispatch_open`/`dispatch_close` pair (§6), first open
to last close so a story's fix iterations are included. Unscoped, `usage` still prints the total
— it is useful for a whole-session sanity check — but labels it and **withholds the `--tokens-*`
flags**, since those are what gets pasted into `set-actual`. A node with no bracket in
`events.jsonl` is refused outright: there is nothing to cut the session down to.

Subagent turns are **not** in the parent transcript. They live in
`<session-id>/subagents/agent-*.jsonl`, carry the same `sessionId`, and are resolved
automatically — reading only the parent file reported `sidechain=0` on every run and omitted
every dispatched agent's spend.

It prints the four class totals and the exact `--tokens-*` flags to paste into `set-actual`.

"Read the usage fields and sum them" is not an executable instruction, and an agent asked to
follow it by hand hit all three traps in the file format at once. Two inflate and one
deflates, so the errors partly cancel and the result looks plausible rather than broken.

| Trap | Direction | What actually happens |
|---|---|---|
| **Which transcript is mine** | **unrelated** | The first and worst. Pointed at a task `.output` artifact rather than a session transcript, a count reported an output figure several times below what the running agent reported — while the cache figures matched closely, so nothing looked wrong. Not arithmetic: file choice. |
| One message, many records | **inflates** | A streaming message is rewritten repeatedly with the same `message.id` and identical `usage`. A real transcript held 2,482 assistant records for 953 distinct ids — summing records overstates by ~2.6×. |
| `cache_creation` twice | **inflates** | `usage` carries both flat `cache_creation_input_tokens` and a nested `cache_creation` mapping. They are the same tokens (equal in 2,482 of 2,482 records). Adding both double-counts the most expensive class. |
| Subagent turns missed | **deflates** | Dispatched work is recorded with `isSidechain: true`, often in a different file. Reading one file, or filtering sidechains out, drops whole phases. |

**Identity is checked before arithmetic.** With no path, `usage` resolves this session's own
transcript from `$CLAUDE_CODE_SESSION_ID` — every record carries a `sessionId` and the file is
named for it, so a session can identify its transcript exactly rather than be told. With a
path, it verifies the file *is* a session transcript and belongs to the expected session, and
**refuses (exit 2) rather than guess**: a file carrying no `sessionId` is named as the
`.output`-artifact shape, a file belonging to another session is named with that session's id,
and a file mixing sessions is reported as malformed. `--allow-unidentified` overrides
deliberately, and then the output labels itself `UNVERIFIED` rather than printing a session id
it never checked.

A reader that can be aimed at the wrong file does not fix trap 1 — it moves it one step
earlier. Refusing is the fix.

`usage` also dedupes by message id, reads only the flat cache field, counts sidechain records,
and accepts directories so a run split across files is summed whole. Pass every transcript the run
touched — it reports `files`, `records`, `unique` and `sidechain` counts so the read is
checkable, and warns when a single file contains no sidechain turns at all.

## 4. Writing estimates and actuals

All writes go through `pm-status.py`. Never hand-edit a state file.

**`set-estimate` is the direct, manual write** — pass every field yourself. The bottom-up
flow (`step-estimate.md`) does not call it: it uses `estimate-story` (classification in,
band × calibrated ratio × fix factor out, `cost` priced from the resulting `tokens_k`) and
`estimate-rollup` (children in, closure- and orchestration-widened range out, `cost` priced
from the rolled-up `tokens_k` range) instead, so the arithmetic runs once, in `pm-status.py`,
not in step-file prose. `set-estimate` still exists for a manual override or any write outside
that flow.

```bash
# story estimate — single-value aliases
python3 {pm_status} set-estimate --state-root {pm_state_root} \
  --story E001-S01-003 \
  --man-hours 6 --hitl-hours 0.8 --elapsed-hours 1.5 --tokens-k 320 \
  --confidence high

# sprint or epic estimate — ranges
python3 {pm_status} set-estimate --state-root {pm_state_root} \
  --epic E001 [--sprint S01] \
  --man-hours-low 12 --man-hours-high 18 \
  --hitl-hours-low 1.5 --hitl-hours-high 2.5 \
  --elapsed-hours-low 2.5 --elapsed-hours-high 4 \
  --tokens-k-min 600 --tokens-k-max 950 \
  --confidence high

# actual — same metric flags at every level; tokens are per-class, cost is derived
python3 {pm_status} set-actual --state-root {pm_state_root} \
  --node {story|sprint|epic} (--story KEY | --epic ID [--sprint ID]) \
  --runtime {runtime} \
  --elapsed-hours 3.2 --man-hours 15 --hitl-hours 1.8 \
  --tokens-input 122 --tokens-output 41 --tokens-cache-write 244 --tokens-cache-read 405 \
  --model claude-sonnet-5

# orchestration block — sprint/epic only, never story; --man-hours 0 always (AI-only overhead)
python3 {pm_status} set-actual --state-root {pm_state_root} \
  --node {sprint|epic} --epic ID [--sprint ID] --block orchestration \
  --runtime {runtime} \
  --elapsed-hours 0.6 --man-hours 0 --hitl-hours 0.1 \
  --tokens-input 14 --tokens-output 5 --tokens-cache-write 27 --tokens-cache-read 44 \
  --model claude-sonnet-5
```

`--cost`/`--cost-low`/`--cost-high` on either subcommand are **rejected, exit 2** — "cost is
derived from tokens x rates and cannot be set directly." Fix the token counts or
`modules.l3io-pm.token_rates` instead.

Node kind for `set-estimate` is **inferred** from which selector flags are present
(`--story` → story; `--epic` with or without `--sprint` → sprint/epic). `set-actual` takes
an explicit `--node`.

**`--block {actual,orchestration}`** (default `actual`) selects which block `set-actual`
writes. `--block orchestration` on a story node is a **usage error, exit 2** — a story's
orchestration overhead belongs to its parent sprint, not to itself. Everything else about the
call (flags, calibration side effect, event logging) works the same for either block; only the
target block and which calibration component samples (§8) differ.

**Flag/kind mismatches are silently ignored, not rejected.** On a story node the range
flags are dropped; on a sprint or epic node the single-value flags are dropped. `--tokens-k`
and `--tokens-k-min` share an argparse destination (the alias exists for the story form), so
passing both in one `set-estimate` call means the last one parsed wins. Use exactly the form
that matches the node kind.

`--confidence` is optional. When omitted and no confidence is already set, it is **derived**:
`medium` if every field for that kind is present, `low` otherwise. It is never derived as
`high` — pass `--confidence high` explicitly when the calibration data justifies it (§8). The
completeness check names only the fields `set-estimate` can actually write — the four
calibrated metrics (story form) or their eight range keys (sprint/epic form). `cost` is in
neither list: `set-estimate` rejects `--cost*` outright, so requiring it would have made every
hand-written estimate permanently `low` no matter how complete it was, and the derivation could
only ever have reported one of its two values.

Write the actual, the completion evidence, and the status transition as separate calls, then
gate on `verify`. Story closeout additionally requires `completion_evidence` (written via
`set-field`), which `verify --scope story` checks.

## 5. Enforcement — what is actually checked, and where

The HARD RULE is enforced in **two halves**. Neither half alone is sufficient, so both must
run.

### Half 1 — `set-actual`, at write time

Under `--runtime claude`, passing `--tokens-na` (in place of the `--tokens-*` counts) is a
**usage error, exit 2**, with a message pointing at the exact per-class capture procedure in
this file. Also under `--runtime claude`, giving **any** `--tokens-*` flag requires **all
four** — a partial set is a usage error, exit 2, naming the missing flags. An explicit `0` is
a valid value: the requirement is that the capturer looked at all four classes, not that all
four are nonzero. Without this, an omitted class was silently zero-filled, `total` summed only
what was passed, `cost` derived from that, and `verify` then confirmed all three agreed with
each other — internally consistent and therefore unfalsifiable, while understating the node by
an order of magnitude (cache classes dominate real runs). `--runtime other` stays permissive: a
runtime that exposes only some classes is exactly what it is for.

`--cost`/`--cost-low`/`--cost-high` are rejected on **every** runtime, unconditionally — cost
has no runtime exemption because it is never entered at all.

Limits of this check, which the orchestrator must compensate for:

- It only inspects metrics **actually passed**. `set-actual` requires at least one of
  `--elapsed-hours`/`--man-hours`/`--hitl-hours`/`--tokens-*`/`--tokens-na`, not all of them —
  under `--runtime claude`, omitting the token flags *entirely* still succeeds (exit 0); only a
  partial class set is rejected. Always pass every metric in one call.
- It does not apply to `elapsed_hours`, `man_hours`, or `hitl_hours`; those are caught later by
  `verify`, which requires them to be numeric on every runtime.

### Half 2 — `verify`, at read-back

`verify` is the completeness gate. `--scope story` and `--scope sprint` check **completion
of one node**:

- `status == done`
- all five `actual.*` fields **present**
- `elapsed_hours`, `man_hours`, and `hitl_hours` numeric and not `N/A`
- `tokens_k` and `cost` may be `N/A` **only** under `--runtime other` and without
  `--require-tokens`; `--runtime claude` or `--require-tokens` makes `N/A` a failure
- when `tokens_k` is the structured mapping, `tokens_k.total` must equal the sum of its four
  classes (tolerance 0.01, wider than `cost`'s because `total` is rounded at write time and an
  unrounded re-sum can legitimately differ by up to half the last decimal place)
- when `tokens_k` is present but is **not** the mapping and not `N/A` — a bare scalar, the
  pre-rework shape — it **fails** under `--runtime claude` or `--require-tokens`. There is no
  class split to price, so the cost invariant below cannot run at all, and skipping it was a
  one-line way around design §4.3's "a hand-edited cost cannot survive": `tokens_k: 500` beside
  `cost: 9999.99` used to return PASS. The scalar form stays valid under `--runtime other`,
  where `set-estimate` writes it and a runtime with no per-class visibility has nothing better
- `cost` must equal what `tokens_k` prices out to under the node's own `model` and the
  effective rate table (tolerance $0.005 — half of the smallest unit either figure can carry).
  A hand-edited `cost`, or a `tokens_k` edited without re-deriving `cost`, fails here. A missing
  `model` when `tokens_k` is structured also fails ("cost cannot be verified")
- `completion_evidence` present (story scope only)

```bash
python3 {pm_status} verify --state-root {pm_state_root} \
  --scope {story|sprint} (--story KEY | --epic ID --sprint ID) \
  --runtime {runtime} [--require-tokens] [--token-rates JSON]
```

`--scope epic` is a **different check**: it walks the epic's whole subtree and validates
structural / back-reference integrity (every sprint directory has a `sprint.yaml`; every
sprint and story file carries `epic:`/`sprint:` back-references matching its directory). It
does **not** look at `status`, `estimate`, or `actual` at all. See `status-files.md` §7.

Exit codes (identical across all subcommands):

| Code | Meaning |
|---|---|
| `0` | Success / verified |
| `2` | Usage error — including `runtime=claude` + `--tokens-na`, and any `--cost*` flag |
| `3` | Node not found |
| `4` | Verification failure (missing/invalid field, cost/token mismatch, or structural mismatch) |
| `5` | Epic locked by another session |

### What is *not* enforced

- **No machine check on the `estimate` block, ever.** `verify` inspects `actual` only.
  `set-estimate` has no required flags and never fails on an incomplete estimate — it
  records `confidence: low` instead. The estimate half of the HARD RULE is orchestrator
  discipline, as is the anti-anchoring read-order for `man_hours` (§2) — no script checks
  either.
- **No metric check at epic scope.** Because `verify --scope epic` is structural, the
  epic-level actual has no read-back gate. Close an epic by running
  `verify --scope sprint` on every sprint, then writing the epic actual and confirming it
  by reading the node back.
- **No calibration enforcement.** `set-actual` derives and appends a calibration sample by
  default, but nothing forces the caller to keep that on — `--no-calibrate` suppresses it
  silently, and a derivation that fails (bad estimate shape, no comparable actual) only warns
  on stderr; the actuals write still succeeds. See §8.

## 6. The estimation roll-up

**Estimates are bottom-up.** Sprint and epic estimates are *defined as* the sum of their
children plus a closure band plus an orchestration band, so they reconcile with their children
by construction. Do not compute a sprint or epic estimate by any independent formula —
parallel formulas drift.

Per calibrated metric (`elapsed_hours`, `man_hours`, `hitl_hours`, `tokens_k` — never `cost`,
which is priced separately, below):

```
story.estimate  = base_band(classification) × scope_ratio × fix_mult
sprint.estimate = Σ story.estimate + calibrated sprint-closure band + calibrated orchestration band
epic.estimate   = Σ sprint.estimate  + calibrated epic-closure band + calibrated orchestration band
```

### Attribution — which spend belongs to which block

The estimate above has three terms, so the actuals must have three matching buckets, and every
unit of spend must land in **exactly one** of them. This is what makes the estimate and the
actual comparable at all, and it is what `derive_closure_sample` and
`record_orchestration_sample` each measure their own component from.

| Bucket | Where it is recorded | What belongs in it |
|---|---|---|
| children | each child node's own `actual` | everything a story (or, one level up, a sprint) spent on itself |
| closure | **inside the parent's `actual`, on top of the children's sum** | the closing level's own closure phases — adversarial analysis, QA generation, retrospective, the fix passes they trigger |
| orchestration | the parent's separate `orchestration` block | the orchestrator's own coordination: dispatching subagents, deciding, and waiting on them |

> **A parent's `actual` is `Σ children + that level's own closure-phase spend` — never the
> bare sum.** Writing the bare sum attributes the closure phases' spend to nothing at all:
> not to a child, not to the parent, not to `orchestration` (a different bucket, per the table
> above). The closure component is measured from exactly that residual, so a bare sum makes it
> identically zero and, after three closes, trains the closure band to contribute nothing to
> every future estimate. `set-actual` refuses a zero residual for this reason (§8), and the
> closure step files
> (`steps/sprint/step-04-sprint-closure.md` §3, `steps/execute/step-06-epic-closure.md` §3)
> state the sum-plus-closure rule per metric.

`man_hours` is the one exception, and it is not a sum in the first place: it is the
counterfactual re-assessment of the whole level (§2), which already covers the closure
work that level delivered. `elapsed_hours`, `hitl_hours`, and the four `tokens_k` classes are
summed and then extended by the closure phases' own measured spend, captured exactly as for a
story (§3).

#### Where the boundary between "child" and "orchestration" is

**Every** subagent spawn in the system is bracketed by a `dispatch --event open` immediately
before it and a `dispatch --event close` immediately after, carrying the same
`--agent`/`--epic`/`--sprint`/`--story` identity and closed on every exit path. Those two
records in `events.jsonl` are what make the boundary **unambiguous**.

A bracket records a boundary; it does not by itself name a bucket. The bucket is fixed by the
step that opened the span, so that every spawn site in the system has exactly one defined
home:

| Spawn site | Bucket | Recorded in |
|---|---|---|
| `sprint/step-02-story-prep.md` — `bmad-create-story` (batched per sprint) | child | split evenly across the `actual` of each story the batch enriched |
| `sprint/step-03-dev-loop.md` §2/§3 — dev, code review, fix passes | child | that story's `actual` |
| `execute/step-05-epic-loop.md` §5 — sprint subagent | child | that sprint's `actual` |
| `closure/sprint-closure.md`, `closure/epic-closure.md` — every phase | closure | the parent's own `actual`, on top of the children's sum |
| `execute/step-04-arch-gate.md` — reviewers, ADR subagents | orchestration | the **epic's** `orchestration` block |
| `plan/step-03-story-elaboration.md` | none | planning sits outside the execution roll-up |

Messages **outside every open dispatch** — deciding what to dispatch, reading a result — are
orchestration, and land in the parent's `orchestration` block.

The arch gate is the one entry that needs saying out loud: it is epic-level work that belongs
to no sprint and is not a closure phase, so it has no child `actual` to land in and would
otherwise fall through the rule above into orchestration by default. Recording it there is
deliberate rather than accidental — it is pre-sprint epic overhead, exactly the class of spend
the orchestration band exists to cover, and bracketing it means the band measures it instead
of inferring it.

> **The counts themselves are still read by the agent, from the session transcript — exactly
> as for every other metric.** `pm-status.py` has no access to a session transcript and never
> will; it records the boundary and prices the numbers you hand it, and nothing more. There is
> no derivation from `events.jsonl` to a token count, and any wording implying one is an
> overclaim. The dispatch events remove the *judgement* about where one bucket ends and the
> next begins; they do not remove the *reading*.

Closing on **every** exit path — `DONE`, `BLOCKED`, and `FAILED` alike — is what keeps the
boundary usable. A dispatch left open also disappears from `report --stall-minutes` the moment
a retry reuses its identity, taking the original hang's timestamp with it.

### Base bands (cold-start priors, per story)

`BASE_BANDS` in `pm-status.py` is the single source for these — do not copy the numbers into
a second table that can drift out of sync. It has **no `cost` row** — see "Pricing `cost`"
below. `estimate-story` reads it directly:

```bash
python3 {pm_status} estimate-story --state-root {pm_state_root} \
  --story {story_key} --classification {simple|standard|complex} \
  [--confidence {low|medium|high}] [--model ID] [--token-rates JSON]
```

| Classification | man_hours | hitl_hours | elapsed_hours | tokens_k |
|---|---|---|---|---|
| simple | 2–4 | 0.1–0.3 | 0.5–1.5 | 20–50 |
| standard | 4–8 | 0.2–0.5 | 1–3 | 40–100 |
| complex | 8–16 | 0.3–1.0 | 2–6 | 80–200 |

The model's only job is choosing the classification; `estimate-story` looks up the band,
applies the calibrated `scope_ratio` (per metric) and `fix_factor`, and writes the estimate
block. See §8 for how those two multipliers are derived.

Stories store the band **midpoint × ratio × fix** as a single value per metric; ranges appear
only at sprint and epic level.

**`estimate-story` records one ratio PER CALIBRATED METRIC**, as `estimate.scope_ratios`. This
is load-bearing, not provenance: `derive_story_sample` divides the applied ratio back out so the
next sample is measured against the base band (§8), and four independently calibrated metrics
cannot be reconstructed from one recorded number. A scalar `scope_ratio` (what
`set-estimate --scope-ratio` writes, or an estimate written before per-metric ratios existed)
is still *read* as a fallback for every metric, but `estimate-story` no longer writes it.

### Pricing `cost`

`cost` is **not** one of the banded/calibrated metrics. `estimate-story` prices it by splitting
the banded `tokens_k` total across the four classes — using `observed_mix` (the mean observed
split once ≥3 story samples carry class data) or, below that, the cold-start assumption
`COLD_START_TOKEN_MIX = {input: 0.15, output: 0.05, cache_write: 0.30, cache_read: 0.50}` — and
running the split through `cost_from_tokens` for `--model` (falling back to
`DEFAULT_ESTIMATE_MODEL = "claude-opus-5"` when omitted). `estimate-rollup` does the same for
the rolled-up `tokens_k_min`/`tokens_k_max` range. This keeps `cost` arithmetically bound to
the token estimate it prices — it cannot drift apart from it the way an independently banded
and independently calibrated cost figure could (and, before this rework, did).

#### The band is FRESH tokens; `cache_read` is projected, not banded

`BASE_BANDS`' `tokens_k` numbers (20–200k) are **fresh tokens** — `input + output +
cache_write` — and always were. `cache_read` is not in them and must never be added to them.

The reason is what each measures. Fresh tokens track how much work a story asks for.
`cache_read` tracks corpus size × agent count: how much context each dispatched agent
re-reads, which is the same whether the story touches one file or ten. It is an
orchestration driver wearing a scope metric's clothes.

Leaving that unstated cost a real project its estimates. Actuals are captured
cache-inclusive, so the scope ratio was computing `cache_inclusive_actual / fresh_band` —
a basis gap of roughly three orders of magnitude, absorbed in silence because a ratio has
no units to disagree about. One story measured **182,121k tokens, 97.4% of it cache reads**.
The per-class split is what proved it was a basis error rather than signal: only the bucket
whose samples straddled the accounting change moved, reading **285.291 across five samples**
against `standard`'s **7.386 across three** that did not.

So, on both sides of the ratio:

- **`derive_story_sample`** measures the fresh sum of the actual against the fresh sum of the
  estimate. Not `tokens_k.total`, on either side — the cancellation to `actual / band_mid`
  only holds while the denominator is the banded quantity, and since the estimate now carries
  a projected `cache_read` on top, its `total` no longer is.
- **`estimate-story`** bands fresh tokens, splits them across the three fresh classes by the
  mix renormalized over those three, then projects `cache_read = fresh × (mix.cache_read /
  mix.fresh_share)`. The estimate's `total` therefore *exceeds* its band, which is correct
  and is the visible sign the two are on the same footing.

Samples recorded before this are unrecoverable — a stored sample is a bare rounded ratio with
no raw counts behind it — so the purge drops `scope.*.tokens_k` once, under its own
marker, keeping every other component and every `token_mix` sample. It runs automatically on
the next sample write, and `pm-status.py calibration migrate-metrics` triggers it explicitly. Until that
purge runs, `active_scope_ratio` refuses to apply a `tokens_k` ratio at all, so a read-only
`estimate-story` falls back to cold start rather than applying a poisoned one.

`COLD_START_TOKEN_MIX` is an **assumption, not a measurement** — it affects only how a banded
fresh total is *split*, and what `cache_read` is projected against, never the band itself.
Note how far it sits from the one project measured so far (0.50 assumed against 0.974
observed): it is superseded by `observed_mix` after three story closes, and that supersession
is the mechanism, not a fallback. `observed_mix` reads
`cal["token_mix"]["samples"]`, a list of per-story observed class fractions recorded by
`record_story_sample` whenever a story's actual `tokens_k` mapping has a positive `total`; it
is a derived statistic, not a calibration *component* — it has no activation threshold beyond
requiring ≥3 usable samples (`MIN_SAMPLES`), and it never appears in `CALIBRATED_METRIC_FIELDS`.

### Roll-up mechanics

`estimate-rollup` computes the sprint/epic range from its children plus a closure band plus an
orchestration band:

```bash
python3 {pm_status} estimate-rollup --state-root {pm_state_root} --epic {epic_key} --sprint {sprint_key} [--model ID] [--token-rates JSON]
python3 {pm_status} estimate-rollup --state-root {pm_state_root} --epic {epic_key} [--model ID] [--token-rates JSON]
```

For each calibrated metric:

- `total` = Σ child estimate for that metric (a story's single value, or a sprint's range
  midpoint).
- Closure band: apply the calibrated `closure` ratio for that level when it has activated
  (`total × (1 + ratio × band)`); otherwise the cold-start band applies at both ends, which
  is the same formula at `ratio = 1.0` (`COLD_START_CLOSURE_BAND = (0.10, 0.25)` —
  **10%/25% at every level**, sprint and epic alike; there is no separate 15%/20% split).
- Orchestration band: apply the calibrated `orchestration` **fraction** for that level when it
  has activated (`total × fraction × ORCH_SPREAD`, `ORCH_SPREAD = (0.8, 1.2)`); otherwise it
  contributes **nothing** — there is no cold-start prior for orchestration, unlike closure (see
  §8's `active_orchestration_fraction` for why: every measurement available when this was
  designed was contaminated by a cache-eviction defect, so there was nothing safe to seed a
  prior from). `estimate-rollup` warns on stderr, naming the inactive metrics, whenever
  **any** calibrated metric's orchestration component is still unseeded at that level — this
  estimate is known-low on those metrics until real observations exist.
- The combined low/high bound for a metric is:
  `total × (1 + closure_ratio × COLD_START_CLOSURE_BAND[i] + orch_fraction × ORCH_SPREAD[i])`
  for `i` = low, high.
- The applied closure ratios and orchestration fractions are recorded per metric as
  `estimate.closure_ratios` and `estimate.orchestration_ratios`, for the same reason
  `estimate.scope_ratios` exists on a story: the closure/orchestration sample divides them
  back out (§8).

`cost_low`/`cost_high` are then priced from `tokens_k_min`/`tokens_k_max` as described above,
under "Pricing `cost`."

## 7. The fix reserve

`F` (default **1.25**) reserves headroom for the fix loop — the rework a story needs after
code review and QA findings.

**`F` is a cold-start prior only.** It fills the gap before a component has ≥3 calibration
samples. Once the learned ratios activate they already encode observed fix overhead, because
they are measured against actuals that *include* the fix loop.

> **Never stack `F` on top of an activated learned ratio.** Doing so double-counts fixes and
> inflates every downstream estimate. `fix_mult` is `F` **or** the learned factor, never
> their product.

Precisely:

```
fix_mult = F (1.25)                       if the fix component for this classification is not active
fix_mult = calibration.fix.avg_fix_factor if it is active
```

Activation for `fix` is stricter than for `scope`/`closure`/`orchestration` — see §8 for why it
needs **both** cohorts (`clean` and `reworked`) at ≥3 samples, not just ≥3 samples of one thing.

**`fix_mult` applies to every calibrated metric** — `estimate-story` multiplies each of
`man_hours`, `hitl_hours`, `elapsed_hours`, and `tokens_k` by the same `scope_ratio ×
fix_mult` for that metric. `cost` has no `fix_mult` of its own to apply: it is priced from the
already-fix-adjusted `tokens_k`, so the fix reserve reaches it indirectly, through the token
total it prices.

## 8. Calibration

`pm-status.py` runs the calibration loop itself — deriving a sample on every `set-actual`,
weighting it, and applying whichever components are active at estimate time. A run never has
to do any of it by hand, which is why the model lives in its own file rather than here:

> **Full model: `references/calibration-model.md`.** Read it to explain a calibration result,
> to diagnose a `provenance=` or `no ... sample:` note on `set-actual`'s stdout, or to run the
> one-time metrics migration. It is not needed to capture metrics correctly.

What a step file needs to know inline:

- **Four components**, each learned per metric: `scope` (story sizing, per classification),
  `closure` (per level), `fix` (per classification, as `clean`/`reworked` cohorts), and
  `orchestration` (per level, a *fraction* of children rather than a ratio — its band ships
  unseeded).
- **Activation is ≥3 samples**, exponential-decay weighted. Below that a component stays on
  its cold-start prior. `fix` needs both cohorts at ≥3.
- **`cost` is never calibrated.** It is derived from `tokens_k × rates`, so a second learned
  copy could only disagree with the tokens it prices.
- **Every sample is replay-guarded** by a marker written onto the node. A second `set-actual`
  on the same node records nothing and says so — a retry is safe, and never skews a ratio.
- **Write `completion_evidence.fix_iterations` before `set-actual`**, or the scope-versus-fix
  split cannot see it and the fix factor stays frozen at the cold-start prior, silently.
- **It must be a number, and `set-field` now enforces that.** Stored as text the field still
  looked right on disk while reading as `provenance=backout` on a story that needed no rework —
  dividing its scope ratio by a 1.25 fix factor it never incurred, and leaving the `clean`
  cohort empty so `fix` could never activate. `set-field` coerces the value and rejects
  anything that is not a non-negative whole number, an unsubstituted template placeholder
  included. To repair samples already recorded that way, run `pm-status.py calibration
  redrive --state-root S`: the nodes still hold every input, so `scope` and `fix` are derived
  again rather than discarded.
- **The file** is `{implementation_artifacts}/state/pm-calibration.yaml`, committed, shared
  across every epic and parallel subagent; every write takes flock.

## 9. Where `CLAUDE.md` and the code disagree

Documented rather than papered over. In each case the code is authoritative.

1. **"This is enforced, not optional" is true at story and sprint level only.** There is no
   read-back gate on an epic's `actual` block (`verify --scope epic` is structural), and no
   gate on any `estimate` block at any level.

2. **`set-actual` does not require all five metrics.** It requires *at least one*. The
   `--runtime claude` rejection only fires on tokens, and only when tokens were actually
   passed as `--tokens-na`.

3. **`--runtime` defaults to `other`.** The strict path is opt-in per call. A `set-actual`
   or `verify` invocation that forgets `--runtime {runtime}` silently runs permissive.

4. **No `retrospective`-level metric block exists.** See §1.

5. **`--require-tokens` on `verify` is undocumented in `CLAUDE.md`.** It forces the
   Claude-strict token rule irrespective of `--runtime`.

6. **The anti-anchoring read-order for `man_hours` (§2) is agent discipline, not a script
   check.** Nothing in `pm-status.py` inspects when a node's estimate was read relative to
   when its actual was formed; the closure step files enforce the ordering by instruction, not
   by any mechanism `verify` can see.

## 10. Worked example

Story `E001-S01-003`, classification `complex`, cold-start `fix` (no calibration file yet
covers this classification), but `scope.complex.man_hours` already active at ratio `1.10`
(≥3 samples); every other `scope` metric for `complex` is still cold-start (ratio `1.0`).

**Estimate.** The model supplies only the classification:

```bash
python3 {pm_status} estimate-story --state-root {pm_state_root} \
  --story E001-S01-003 --classification complex
# OK estimate-story E001-S01-003 class=complex scope_ratios[man_hours=1.1 hitl_hours=1.0 elapsed_hours=1.0 tokens_k=1.0] fix_factor=1.25
```

`estimate-story` looks up `BASE_BANDS["complex"]` (man_hours 8–16, hitl_hours 0.3–1.0,
elapsed_hours 2–6, tokens_k 80–200), takes each midpoint, and multiplies by that metric's own
scope ratio and the classification's fix multiplier — `fix_mult` = `F` = `1.25` here, since
`fix` has no active cohorts yet:

```
man_hours     = 12    × 1.10 × 1.25 = 16.5      (scope ratio active)
hitl_hours    = 0.65  × 1.00 × 1.25 =  0.81      (scope ratio cold-start)
elapsed_hours =  4    × 1.00 × 1.25 =  5.0       (scope ratio cold-start)
tokens_k      =140    × 1.00 × 1.25 =175         (scope ratio cold-start, rounded to int)
```

`cost` is then priced from that 175K `tokens_k` total: split across the four classes by
`observed_mix` (or, below 3 samples, `COLD_START_TOKEN_MIX`) and run through `cost_from_tokens`
for the model bound at estimate time (`--model`, or `DEFAULT_ESTIMATE_MODEL` if omitted) —
say `cost = 0.72` under the cold-start mix and `claude-opus-5` rates (175K splits to
26/9/52/88 across input/output/cache_write/cache_read, priced at $5/$25/$6.25/$0.50 per M).

The written `estimate.scope_ratios` is `{man_hours: 1.1, hitl_hours: 1.0, elapsed_hours: 1.0,
tokens_k: 1.0}` — one entry per calibrated metric, each the ratio actually applied to that
metric. The sample derivation reads these back individually; a single recorded number could
not reconstruct four different corrections.

**Actual.** The story runs under Claude, needs **one** fix iteration
(`completion_evidence.fix_iterations: 1`, written via `set-field` before closeout). The
closing agent first re-assesses `man_hours` — reviewing the delivered diff and tests, before
reading the estimate above — and settles on 18.2 as the counterfactual developer-hours figure.
Compute hours (6.1) and human-attention hours (0.9) are read from the run itself, and the four
token classes (say totaling 171K) are read from the transcript `usage` fields:

```bash
python3 {pm_status} set-actual --state-root {pm_state_root} \
  --node story --story E001-S01-003 --runtime claude \
  --elapsed-hours 6.1 --man-hours 18.2 --hitl-hours 0.9 \
  --tokens-input 26 --tokens-output 9 --tokens-cache-write 51 --tokens-cache-read 85 \
  --model claude-opus-5
# OK set-actual E001-S01-003 ['cost', 'elapsed_hours', 'hitl_hours', 'man_hours', 'model', 'tokens_k'] [scope+4 metrics, provenance=backout, class=complex]

python3 {pm_status} set-status --state-root {pm_state_root} \
  --story E001-S01-003 --status done

python3 {pm_status} verify --state-root {pm_state_root} \
  --scope story --story E001-S01-003 --runtime claude
# PASS E001-S01-003
```

Had `--tokens-na` been passed with `--runtime claude`, `set-actual` would have exited **2**
before writing anything, and no calibration sample would have been derived. Had `--cost 1.24`
been passed instead of letting it derive, `set-actual` would have exited **2** for the same
reason — cost is never an input.

**What `set-actual` derived, inline.** `fix_iterations` is `1`, not `0`, so this is the
**backout** path: the actual mixes scope and rework, the scope portion is `actual ÷
fix_factor`, and the `fix_factor` cancels out of the ratio. Each calibrated metric divides its
own applied `scope_ratios` entry back out, so the comparison lands against the base band:

```
man_hours scope ratio     = 18.2 × 1.10 /  16.5 = 1.2133   ( = 18.2 /  (12   × 1.25) )
hitl_hours scope ratio    =  0.9 × 1.00 /  0.81 = 1.1111   ( =  0.9 / (0.65  × 1.25) )
elapsed_hours scope ratio =  6.1 × 1.00 /  5.0  = 1.2200   ( =  6.1 /  ( 4   × 1.25) )
tokens_k scope ratio      =  171 × 1.00 / 175   = 0.9771   ( =  171 / (140   × 1.25) )
```

Each is appended to `scope.complex.{man_hours,hitl_hours,elapsed_hours,tokens_k}.samples`.
Because `fix_iterations > 0`, the 18.2 man-hours actual also updates
`fix.complex.reworked`'s running mean — not `clean`'s — and `fix.complex.clean` gets nothing
from this story. `fix` for `complex` only activates once **both** `clean` and `reworked`
separately reach 3 samples; a run of reworked-only stories, however many, never activates it
on its own.

Had `fix_iterations` been `0`, provenance would have been `exact`, the man-hours actual would
have fed the `clean` cohort, **and the four ratios would differ** — the exact path keeps the
`fix_factor` because a zero-rework actual is pure scope measured against a
fix-reserved estimate:

```
man_hours scope ratio (exact) = 18.2 × 1.10 × 1.25 / 16.5 = 1.5167   ( = 18.2 / 12 )
```

A second `set-actual` on this story would record nothing: the node now carries
`calibration_sampled_at`, and the call reports `sample already recorded at … — skipped
(replay)`.

**Orchestration, at sprint closure.** Suppose this story's sprint closes with an
`orchestration` block recording `elapsed_hours: 0.6`, and the sprint's children (this story
plus its siblings) sum to `elapsed_hours: 5.4` in their own `actual` blocks. Assuming
`orchestration.sprint.elapsed_hours` has already cleared 3 samples elsewhere, the sample this
closure adds is `0.6 / 5.4 = 0.1111` — a fraction, appended to
`orchestration.sprint.elapsed_hours.samples`, not divided against any estimate (there is
nothing to divide out — see §8). If any sibling story is missing its `elapsed_hours` actual,
this metric is skipped for this sample entirely, rather than computed from a partial sum.
