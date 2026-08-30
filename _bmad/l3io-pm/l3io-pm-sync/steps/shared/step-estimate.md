# Step: Estimate

Communicate all responses in `{communication_language}`.

Callable from l3io-pm-plan and l3io-pm-execute. Computes and writes estimate blocks for
stories, sprints, and epics in scope. All arithmetic — base band lookup, calibrated scope
ratio and fix factor per metric, closure band — runs inside `pm-status.py`; this step's job
is to choose scope and classification and call it.

**Input bindings required before calling this step:**
- `{scope}` — what to estimate: `all`, `E{nnn}`, or `E{nnn}-S{nn}`
- `{pm_state_root}`, `{pm_status}`, `{work_type}` — from step-00-activate and step-01

---

## 1. Determine stories in scope

Based on `{scope}`:
- `all` → all stories under every epic in `{pm_state_root}/planned/` and `{pm_state_root}/active/`
  that are not `status: done`
- `E{nnn}`: if `{reestimate_story_keys}` is bound, take **exactly** those keys and no
  others — the caller has already decided what needs re-pricing. If it is not bound, take
  every story under the epic whose `status` is `backlog` or `ready-for-dev`.

  In neither case does this step select a story at `in-progress`, `review` or `done`.
  Selecting `done` stories was the previous behaviour and it is wrong twice over: it
  re-prices work whose actual is already recorded, and it overwrites the estimate that
  actual is measured against, so the variance that trains the next calibration cycle is
  destroyed by the act of measuring.
- `E{nnn}-S{nn}` → all stories under that sprint's directory

Story files are the `*.yaml` files in a sprint directory, excluding `sprint.yaml` (see
`references/status-files.md` §4).

For each story, read its `classification` (simple/standard/complex) and any existing
estimate block.

## 2. Estimate stories (bottom-up)

For each story in the selected set — **whether or not it already carries an `estimate`
block**. `estimate-story` overwrites unconditionally (`node["estimate"] = est`), which is
exactly what re-estimation needs; there is no "needs re-estimation" flag to test and none is
required. Note this is deliberately the opposite of `steps/sprint/step-02-story-prep.md` §4,
which skips a story that is already estimated: prep is priming a story about to be built, and
re-estimation is re-pricing one that has not started. Both are right for their caller.

The model supplies only the classification — `estimate-story` does the rest: looks up the base band
(`references/metrics-contract.md` §6 cites `BASE_BANDS` in `pm-status.py` as the single
source), applies the calibrated per-metric scope ratio and the classification's fix factor
(cold-start priors when either is not yet active), and writes the estimate block.

```bash
python3 {pm_status} estimate-story \
  --state-root {pm_state_root} \
  --story {story_key} \
  --classification {simple|standard|complex} \
  --model {model} \
  [--token-rates '{token_rates_json}'] \
  [--confidence {low|medium|high}]
```

`--model {model}` and `--token-rates` are the bindings from `step-00-activate.md` §1
(`modules.l3io-pm.default_model` / `.token_rates`). Pass `--model` always; add
`--token-rates` only when `{token_rates_json}` is non-empty. Omitting `--model` prices the
derived `cost` at `claude-opus-5` whatever the project actually runs on — a silent ~2× error
on a fable or fast-mode project, which is exactly what keying rates by model prevents.

`--confidence` is optional, and **omitting it writes no `confidence` field at all** —
`estimate-story` records it only when it is passed. (The `medium`/`low` derivation from field
completeness belongs to `set-estimate`, not here; see `metrics-contract.md` §4.) Do not
hand-compute the estimate arithmetic in this step; a re-derivation here can drift from what
`estimate-story` actually applies.

`estimate-story` records the factors it applied — `fix_factor`, plus `scope_ratios` with one
entry per metric — on the estimate block. The calibration sample divides them back out, so
never hand-edit or strip them.

## 3. Roll up sprint and epic estimates

`estimate-rollup` sums the estimates of a node's children and widens the sum by the
calibrated (or cold-start) closure band — see `references/metrics-contract.md` §6 for the
exact mechanics. Run it sprint-first, then epic, since the epic roll-up sums sprint
estimates:

```bash
# each sprint in scope
python3 {pm_status} estimate-rollup --state-root {pm_state_root} --epic {epic_key} --sprint {sprint_key} \
  --model {model} [--token-rates '{token_rates_json}']

# each epic in scope, after all its sprints are rolled up
python3 {pm_status} estimate-rollup --state-root {pm_state_root} --epic {epic_key} \
  --model {model} [--token-rates '{token_rates_json}']
```

Same `--model`/`--token-rates` rule as §2: `--model` always, `--token-rates` only when
`{token_rates_json}` is non-empty. The rolled-up `cost_low`/`cost_high` are priced from the
rolled-up token range under that model.

No `--flock` needed: each epic's estimate write touches only that epic's own directory (see
`references/status-files.md` §9, Concurrency).

## 4. Output estimate summary

After all estimates are written, read each node back (`{pm_status} show`) and output a
summary table:

```
## Estimate Summary (scope: {scope})

| Epic | Sprints | Stories | man-hrs (low–high) | hitl-hrs (low–high) | wall-clock (low–high) | tokens (low–high) | cost (low–high) | confidence |
|------|---------|---------|--------------------|----------------------|-----------------------|--------------------|-----------------|------------|
| E001 | 2       | 8       | 32–52 hrs          | 4–7 hrs              | 9–15 hrs              | 210K–340K          | $2.80–$4.60     | medium     |
| E002 | 3       | 11      | 48–76 hrs          | 6–10 hrs             | 13–21 hrs             | 310K–500K          | $4.10–$6.50     | low        |

**Total (sequential):** 80–128 man-hrs, 10–17 hitl-hrs, 22–36 wall-clock hrs, $6.90–$11.10
**If E001 and E002 run in parallel:** 48–76 man-hrs, 6–10 hitl-hrs, 13–21 wall-clock hrs, $4.10–$6.50
```

`cost` in this table is read back from each node's estimate — never recomputed here. It was
derived once, inside `estimate-story`/`estimate-rollup`, from that node's `tokens_k` and the
model's rate table; this step only reports it.

Confidence levels are per-epic, reflecting the weakest component used.
