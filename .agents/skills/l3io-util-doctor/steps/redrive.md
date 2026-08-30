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

**What it does.** Wraps `python3 {pm_status} calibration redrive --state-root {pm_state_root}`
(`redrive_story_samples` in `pm-status.py`). It:

1. Backs up the current `{pm_calibration_file}` to `pm-calibration.yaml.pre-redrive` — **only**
   if that backup does not already exist. A second run never overwrites the first backup with
   an already-rebuilt file.
2. Resets the `scope` and `fix` components to empty and walks every story node under
   `{pm_state_root}/{active,planned,archived}/epic-*/sprint-*/` (`STATUS_DIRS` — archived
   epics are covered, not just active/planned ones).
3. Re-derives each story's sample from what is on the node today (`estimate`, `actual`,
   `completion_evidence`), through the same `derive_story_sample` function `set-actual` calls
   live, and re-appends the result to `scope`/`fix`.
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
python3 {pm_status} calibration redrive --state-root {pm_state_root}
```

Relay its stdout exactly — it already reports the backup filename (when a backup was
written), stories seen, samples rebuilt, samples skipped, and the provenance breakdown, plus
a closing line confirming `closure`, `orchestration`, and `token_mix` were left untouched.

If the command exits non-zero, treat this as FAILED and stop — do not report DONE.

**Step RD4 — Report**

```
DONE — Calibration redrive complete.
  {relayed stdout from Step RD3}
```

---
