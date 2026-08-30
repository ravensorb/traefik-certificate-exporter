# Step 06: Epic Closure

Communicate all responses in `{communication_language}`.

Run epic-level closure workflow, write actuals, archive the epic, clear the lock, and update
the per-epic calibration file.

## 1. Man-hours re-assessment — do this before anything else touches the estimate

**Required, not a suggestion.** `man_hours` is a **counterfactual** metric: what a developer,
working without AI assistance, would have needed to deliver everything this epic shipped. It
is assessed, not observed, and it is assessed **from the delivered work** — review the epic's
sprints, diffs, tests, and story scope directly. **You must form this number before reading
this epic's `estimate.man_hours_low`/`estimate.man_hours_high`** (or any report that shows
them). Reading the estimate first anchors the re-assessment toward it, which is exactly the
bias this ordering exists to prevent. Bind `{epic_man_hours}` to the result. Only after it is
bound may you read the epic's estimate, for any other purpose (e.g. reporting variance in the
closure report). See `references/metrics-contract.md` §2, §3.

## 2. Load epic-closure workflow

```
{skill-root}/steps/closure/epic-closure.md
```

Execute the full closure workflow from that file. It returns a closure report with:
- Retrospective text
- Any architectural drift findings
- Issue triage results

## 3. Sprint actuals **plus this epic's own closure spend** → write epic actual

```bash
python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key}
```

**The epic actual is the sum of its sprints plus what closing the epic itself cost — never
the bare sum.** Epic closure is real, measurable work: the architectural-drift review, the
epic-level QA, the retrospective, and the fix passes they trigger. If you write the bare sum,
that spend is attributed to nothing — not to a sprint, not to this epic, not to
`orchestration` (§4 scopes that to *dispatching, deciding, and waiting*, which is a different
bucket) — and the residual `pm-status.py` measures the closure calibration component from is
identically zero. `set-actual` now **refuses** a zero residual and says so in its `[...]`
suffix; that message means this step was performed wrong, not that anything is broken.

So, for each metric:

```
epic.actual.<metric> = Σ (done sprints' actual.<metric>) + this epic's own closure-phase spend
```

- `elapsed_hours` — sum the done sprints' `actual.elapsed_hours`, **plus** the wall-clock the
  closure workflow in §2 itself took.
- `hitl_hours` — same shape: the sprints' sum **plus** human attention spent on epic closure.
- `tokens_k` — sum **each of the four classes** across the done sprints (read the per-class
  counts from each sprint's own `sprint.yaml` under
  `{pm_state_root}/active/epic-{epic_nnn}/sprint-*/`; the roll-up above reports only
  `tokens_k.total`, not the split), **plus** the per-class counts the epic closure phases
  consumed, captured from the session transcript's `usage` fields exactly as for a story
  (`references/metrics-contract.md` §3). Sum per class, then pass the four totals — `verify`
  checks that `total` equals the class sum.
- `man_hours` is **not** summed from sprints at all — use `{epic_man_hours}` from §1, the
  epic-level counterfactual re-assessment. A sum of sprint-level counterfactuals does not
  equal the counterfactual effort for the epic as a whole (it omits cross-sprint integration
  work), and the re-assessment already covers the closure work it delivered.

Under `--runtime claude`, pass the summed token classes with `--model`; `set-actual` derives
`cost` — never pass `--cost`. Under any other runtime, pass `--tokens-na` if tokens are not
observable.

```bash
python3 {pm_status} set-actual \
  --state-root {pm_state_root} \
  --node epic --epic {epic_key} \
  --runtime {runtime} \
  --elapsed-hours {total_elapsed} \
  --man-hours {epic_man_hours} \
  --hitl-hours {total_hitl_hours} \
  --tokens-input {total_tokens_input} \
  --tokens-output {total_tokens_output} \
  --tokens-cache-write {total_tokens_cache_write} \
  --tokens-cache-read {total_tokens_cache_read} \
  --model {model} \
  [--token-rates '{token_rates_json}']
```

`{model}` and `{token_rates_json}` are bound at activation (`step-00-activate.md` §1). Pass
`--model` always; add `--token-rates` only when `{token_rates_json}` is non-empty, on this
call, the orchestration call below, and any `verify` on this node.

## 4. Orchestration capture — the orchestrator's own overhead

Separately from the epic actual above, record what the orchestrator itself spent coordinating
this epic (dispatching sprints, deciding, waiting) — time and tokens not already attributed
to any sprint. `--man-hours 0`: orchestration is AI-only overhead, so there is no
human-developer counterfactual for it. Valid on a sprint or epic node only, never a story:

```bash
python3 {pm_status} set-actual --state-root {pm_state_root} --node epic \
  --epic {epic_key} --block orchestration \
  --elapsed-hours {orch_elapsed} --man-hours 0 --hitl-hours {orch_hitl} \
  --tokens-input {orch_tokens_input} --tokens-output {orch_tokens_output} \
  --tokens-cache-write {orch_tokens_cache_write} --tokens-cache-read {orch_tokens_cache_read} \
  --model {model} --runtime {runtime} [--token-rates '{token_rates_json}']
```

This call derives its own calibration sample (the orchestration fraction) and stamps its own
replay marker (`orchestration_sampled_at`), independent of the epic actual's own marker — a
second call on the same node records nothing. See `references/metrics-contract.md` §6, §8.

## 5. Write epic closed + retrospective fields

```bash
python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} \
  --field closed.date \
  --value {today_iso}

python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} \
  --field retrospective.summary \
  --value "{retrospective_summary}"

python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} \
  --field retrospective.learnings \
  --value "{retrospective_learnings}"
```

## 6. Archive epic

`archive-epic` moves the epic's whole directory (epic.yaml, every sprint.yaml, every story
file) from `active/` to `archived/` in one step — nothing to delete afterward, since the
directory itself relocates rather than being copied:

```bash
python3 {pm_status} archive-epic --state-root {pm_state_root} --epic {epic_key}
```

## 7. Clear ownership lock

`archive-epic` moves the directory but does not touch `_lock` — clear it explicitly so the
archived epic's file doesn't carry a stale lock forward:

```bash
python3 {pm_status} clear-lock --state-root {pm_state_root} --epic {epic_key}
```

## 8. Calibration

Nothing to do here — the `set-actual --node epic` call in step 3 already derived and
appended the epic's closure calibration sample, and the `--block orchestration` call in
step 4 already derived and appended its own orchestration sample, both as a side effect of
those writes (unless `--no-calibrate` was passed). Skips are **reported on stdout**, in the
`[...]` suffix of each call's own `OK set-actual …` line, not here and not on stderr. Each
names its metric and its reason (missing sprint actual or estimate, no comparable estimate
range, estimated closure overhead ≤ 0, negative residual, zero residual); a skipped metric
does not stop the others from recording. An `elapsed_hours` skip naming parallel execution is
expected whenever the epic's sprints ran concurrently. A **zero residual** skip is not
expected and is not benign: it means §3's actual was written as the bare sum of the sprints,
omitting this epic's own closure-phase spend. Go back to §3, capture that spend, and re-run
the `set-actual`. If **every** metric was skipped the node carries no
`calibration_sampled_at` marker, so the corrected call records normally; if only some were
skipped the marker is already set and the re-run reports `skipped (replay)` — the actual is
still corrected on disk, but this epic contributes no closure sample for the skipped metrics.
See `references/metrics-contract.md` §8.

## 9. Output

```
Step 06 complete — {epic_key} archived, actuals written, calibration updated
DONE — Epic {epic_key} complete. Sprints: {N}, Stories: {N}, Cost: {total_cost}
```
