## Redrive Mode

Invoked with `redrive` argument. Repairs the `scope` and `fix` calibration components in
`{pm_calibration_file}` for stories whose samples were poisoned by a fixed defect: an older
`set-field` stored `completion_evidence.fix_iterations` as a **string**, and
`derive_story_sample` reads that field to decide a sample's provenance. A story that needed no
rework (`fix_iterations: '0'`, a string) could not compare equal to the int `0`, so it derived
as `backout` instead of `exact` — its scope ratio was divided by a 1.25 fix factor it never
incurred, and the `clean` fix cohort silently never filled. `NUMERIC_NODE_FIELDS` in
`pm-status.py` now coerces this field on every write, so the defect cannot recur, but samples
already recorded under it stay wrong until rebuilt. This mode rebuilds them.

**What it does.** Wraps `uv run {pm_status} calibration redrive --state-root {pm_state_root}`
(`redrive_story_samples` in `pm-status.py`). It:

1. Backs up the current `{pm_calibration_file}` to `pm-calibration.yaml.pre-redrive` — **only**
   if that backup does not already exist. A second run never overwrites the first backup with
   an already-rebuilt file.
2. Resets the `scope` and `fix` components to empty and walks every story node under
   `{pm_state_root}/{active,planned,archived}/epic-*/sprint-*/` (`STATUS_DIRS` — archived
   epics are covered, not just active/planned ones).
3. Re-derives each story's sample from what is on the node today (`estimate`, `actual`,
   `completion_evidence`), through the same `derive_story_sample` function `set-actual` calls
   live, and re-appends the result to `scope`/`fix` **in closure order**, taken from each
   story's `actual` event in `{pm_state_root}/events.jsonl` — not in the order the walk in
   step 2 visits them. Calibration ratios are an exponential-decay mean over samples
   oldest-first, so the last sample in a list weighs most and order is load-bearing.
4. Reports to stdout: stories seen, samples rebuilt, samples skipped (a node that failed to
   parse, or has no estimate/actual pair to derive from), and a provenance breakdown
   (`exact=N backout=M legacy=K`) — a healthy rebuild after this fix should shift stories that
   never needed rework from `backout` to `exact`, not the reverse.

**Limits — read before running:**

- **It rebuilds; it does not merge.** `scope` and `fix` are fully replaced from whatever story
  nodes exist on disk right now. A sample whose story node has since been deleted is gone
  after this runs, not carried forward from the old file — there is nothing left on disk to
  re-derive it from.
- **`closure`, `orchestration`, and `token_mix` are untouched.** They derive from different
  inputs (sprint/epic closure actuals, `--block orchestration` samples, and the token-basis
  migration, respectively) and were never affected by the `fix_iterations` defect —
  `redrive_story_samples` reassigns only `cal["scope"]` and `cal["fix"]`; every other key in
  the calibration file, including its `version` and `granularity`, passes through unchanged.
- **Re-running is harmless.** Each run derives fresh from the same nodes, so running it twice
  in a row, or again after a future `migrate-state`, reproduces the same result rather than
  compounding drift.
- **No calibration file yet is not an error.** A cold-start project has no stories to redrive;
  the command reports zero stories seen and writes no backup.
- **It refuses rather than rebuild in an order it cannot verify.** If any story being sampled
  has no `actual` event in `events.jsonl`, the command exits **2**, writes nothing, and names
  the stories it could not place. Expect this on a project predating the event log, or one
  whose actuals were written with `--no-events`. Directory order is not an acceptable
  fallback: `STATUS_DIRS` is `("active", "planned", "archived")`, so archived epics — the
  oldest work — sort **last** and would collect the **highest** recency weight, inverting the
  weighting rather than repairing it. This was a live defect; a rebuild that repaired nothing
  re-priced a real project's `complex` band by ~16%.
- **Estimates for unstarted stories can move even when no sample changed.** Rebuilding
  restores the correct order, which is itself a change if the file was previously mis-ordered.
  Re-run `estimate-story` afterwards to see current numbers, and expect a diff.

### Steps

**Step RD1 — Load config and resolve state root**

Load config (same as layout cleanup). Resolve `{pm_state_root}` = `{implementation_artifacts}/state`.

If `{pm_state_root}` does not exist:
```
No state directory found at {pm_state_root} — nothing to redrive.
```
Exit.

**Step RD2 — Confirm**

Ask:
```
Rebuild scope and fix calibration samples from the story nodes under {pm_state_root}?
The current calibration file is backed up first (pm-calibration.yaml.pre-redrive, only if
one does not already exist). closure, orchestration, and token_mix are not touched.
  Y — run it
  n — exit, no changes
```

If `n`: print `Redrive cancelled — no changes made.` and exit.

**Step RD3 — Run the redrive**

```bash
uv run {pm_status} calibration redrive --state-root {pm_state_root}
```

Relay its stdout exactly — it already reports the backup filename (when a backup was
written), stories seen, samples rebuilt, samples skipped, and the provenance breakdown, plus
a closing line confirming `closure`, `orchestration`, and `token_mix` were left untouched.

If the command exits non-zero, treat this as FAILED and stop — do not report DONE.

**Exit 2 is a refusal, not a crash, and nothing was written.** It means closure order could
not be established for every sampled story (see the limits above). Relay its message, which
names the stories, and report:

```
BLOCKED: redrive refused — closure order could not be established; calibration unchanged.
  {relayed stderr}
```

Do not offer to re-run it without the event log. A rebuild in directory order is worse than no
rebuild, which is the whole reason it refuses.

**Step RD4 — Report**

```
DONE — Calibration redrive complete.
  {relayed stdout from Step RD3}
```

---
