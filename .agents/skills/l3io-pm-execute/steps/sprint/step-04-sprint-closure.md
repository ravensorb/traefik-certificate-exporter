# Sprint Step 04: Sprint Closure

Communicate all responses in `{communication_language}`.

Run closure phases gated by `{work_type}` and `{skip_phases}`. Write sprint actuals, mark sprint
done, and emit the required status line.

## 1. Man-hours re-assessment — do this before anything else touches the estimate

**Required, not a suggestion.** `man_hours` is a **counterfactual** metric: what a developer,
working without AI assistance, would have needed to deliver everything this sprint's stories
shipped. It is assessed, not observed, and it is assessed **from the delivered work** —
review the sprint's diffs, tests, and story scope directly. **You must form this number
before reading this sprint's `estimate.man_hours_low`/`estimate.man_hours_high`** (or any
report that shows them). Reading the estimate first anchors the re-assessment toward it,
which is exactly the bias this ordering exists to prevent. Bind `{sprint_man_hours}` to the
result. Only after it is bound may you read the sprint's estimate, for any other purpose
(e.g. reporting variance in the closure report). See `references/metrics-contract.md` §2, §3.

## 2. Load sprint-closure workflow

```
{execute_skill_root}/steps/closure/sprint-closure.md
```

Execute it fully. It returns: issues found (with severities), retrospective text, carry_over count.

## 3. Story actuals **plus this sprint's own closure spend** → write sprint actual

```bash
python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key} --sprint {sprint_num}
```

**The sprint actual is the sum of its children plus what closing the sprint itself cost —
never the bare sum.** Sprint closure is real, measurable work: the adversarial analysis, the
QA generation, the retrospective, and the fix passes they trigger. On the motivating run that
was 4% of total spend. If you write the bare sum, that spend is attributed to nothing — not
to a story, not to this sprint, not to `orchestration` (§4 scopes that to *dispatching,
deciding, and waiting*, which is a different bucket) — and the residual `pm-status.py`
measures the closure calibration component from is identically zero. Three such sprints and
the closure band is trained to contribute nothing to every future estimate. `set-actual`
now **refuses** a zero residual and says so in its `[...]` suffix; that message means this
step was performed wrong, not that anything is broken.

So, for each metric:

```
sprint.actual.<metric> = Σ (done stories' actual.<metric>) + this sprint's own closure-phase spend
```

- `elapsed_hours` — sum the done stories' `actual.elapsed_hours` (the roll-up above lists
  them), **plus** the wall-clock the closure phases in §2 themselves took.
- `hitl_hours` — same shape: the stories' sum **plus** human attention spent on closure.
- `tokens_k` — sum **each of the four classes** across the done stories (read the per-class
  counts from each story's own node file; `show` reports only `tokens_k.total`), **plus** the
  per-class counts the closure phases consumed, captured from the session transcript's `usage`
  fields exactly as for a story (`references/metrics-contract.md` §3). Sum per class, then
  pass the four totals — do not add a lump sum to `total` only; `verify` checks that `total`
  equals the class sum.
- `man_hours` is **not** summed from stories at all — use `{sprint_man_hours}` from §1, the
  sprint-level counterfactual re-assessment. A sum of story-level counterfactuals does not
  equal the counterfactual effort for the sprint as a whole (it omits integration and
  cross-story work), and the re-assessment already covers the closure work it delivered.

Under `--runtime claude`, pass the summed token classes with `--model`; `set-actual` derives
`cost` — never pass `--cost`. Under any other runtime, pass `--tokens-na` if tokens are not
observable.

```bash
python3 {pm_status} set-actual \
  --state-root {pm_state_root} \
  --node sprint \
  --epic {epic_key} \
  --sprint {sprint_num} \
  --runtime {runtime} \
  --elapsed-hours {total_elapsed} \
  --man-hours {sprint_man_hours} \
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

Separately from the sprint actual above, record what the orchestrator itself spent
coordinating this sprint (dispatching subagents, deciding, waiting) — time and tokens not
already attributed to any story. `--man-hours 0`: orchestration is AI-only overhead, so there
is no human-developer counterfactual for it. Valid on a sprint or epic node only, never a
story:

```bash
python3 {pm_status} set-actual --state-root {pm_state_root} --node sprint \
  --epic {epic_key} --sprint {sprint_num} --block orchestration \
  --elapsed-hours {orch_elapsed} --man-hours 0 --hitl-hours {orch_hitl} \
  --tokens-input {orch_tokens_input} --tokens-output {orch_tokens_output} \
  --tokens-cache-write {orch_tokens_cache_write} --tokens-cache-read {orch_tokens_cache_read} \
  --model {model} --runtime {runtime} [--token-rates '{token_rates_json}']
```

This call derives its own calibration sample (the orchestration fraction) and stamps its own
replay marker (`orchestration_sampled_at`), independent of the sprint actual's own marker — a
second call on the same node records nothing. See `references/metrics-contract.md` §6, §8.

## 5. Write sprint closed + retrospective

```bash
python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} --sprint {sprint_num} \
  --field closed.date \
  --value {today_iso}

python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} --sprint {sprint_num} \
  --field retrospective.summary \
  --value "{retrospective_summary}"

python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} --sprint {sprint_num} \
  --field retrospective.velocity \
  --value {stories_done}

python3 {pm_status} set-field \
  --state-root {pm_state_root} \
  --epic {epic_key} --sprint {sprint_num} \
  --field retrospective.carry_over \
  --value {carry_over_count}
```

## 6. Mark sprint done

```bash
python3 {pm_status} set-status \
  --state-root {pm_state_root} \
  --epic {epic_key} \
  --sprint {sprint_num} \
  --status done
```

## 7. Calibration

Nothing to do here — the `set-actual --node sprint` call in step 3 already derived and
appended the sprint's closure calibration sample, and the `--block orchestration` call in
step 4 already derived and appended its own orchestration sample, both as a side effect of
those writes (unless `--no-calibrate` was passed). Skips are **reported on stdout**, in the
`[...]` suffix of each call's own `OK set-actual …` line, not here and not on stderr. Each
names its metric and its reason (missing child actual or estimate, no comparable estimate
range, estimated closure overhead ≤ 0, negative residual, zero residual); a skipped metric
does not stop the others from recording. An `elapsed_hours` skip naming parallel execution is
expected whenever the sprint's stories ran concurrently — the sprint's wall-clock is
legitimately below their sum. A **zero residual** skip is not expected and is not benign: it
means §3's actual was written as the bare sum of the stories, omitting this sprint's own
closure-phase spend. Go back to §3, capture that spend, and re-run the `set-actual`. If
**every** metric was skipped the node carries no `calibration_sampled_at` marker, so the
corrected call records normally; if only some metrics were skipped the marker is already set
and the re-run reports `skipped (replay)` — the actual is still corrected on disk, but that
sprint contributes no closure sample for the skipped metrics. Either way, report it in the
closure output rather than treating it as noise. See `references/metrics-contract.md` §8.

## 8. Progress render and report regeneration

**Render (conditional).** Only when `{single_epic_phase}` is `true`. Inside a parallel phase this
output would interleave with sibling epics and is suppressed by design — see §0 of
`step-05-epic-loop.md`. When it is `true`:

```bash
python3 {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format tree
```

**Regenerate the committed report (always, both branches).** Closure is a natural commit point.
Regenerating per story transition instead would churn git on every status move and put parallel
subagents in contention over one file:

```bash
python3 {pm_status} report \
  --state-root {pm_state_root} \
  --plan {planning_artifacts}/plan-output-meta.yaml \
  --format md --out {implementation_artifacts}/progress-report.md
```

That file is a generated view and says so in its own header. Never hand-edit it; regenerate it.
Both commands are read-only with respect to state — a failure in either is a reporting problem,
so note it in one line and continue to the exit status line rather than failing the sprint.

## 9. Required exit status line

```
DONE — Stories: {N}, Issues resolved: {N_resolved}, Issues deferred: {N_deferred}
```
