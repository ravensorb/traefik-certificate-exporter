# Calibration model — how the learned ratios are derived

> **Audience: maintainers and anyone diagnosing a calibration result.** A normal run never
> reads this file. `pm-status.py` performs every step described here itself — deriving each
> sample, weighting it, activating a component, and migrating the file — and reports what it
> did on stdout as a `[...]` suffix. Nothing here is an instruction to an agent; it is the
> specification of machine behavior, kept out of `metrics-contract.md` so that the contract a
> capture agent *does* read stays the size of what it needs.
>
> Canonical order remains: `pm-status.py` > this file > the activation digest.
> `metrics-contract.md` §8 is the summary; this is the model behind it.

## Calibration

### Location

| Binding | Resolves to |
|---|---|
| `{pm_calibration_file}` | `{pm_state_root}/pm-calibration.yaml` = `{implementation_artifacts}/state/pm-calibration.yaml` |

The file is **committed**. Learned ratios are team knowledge and expensive to rebuild —
several closed sprints of real work each. It sits beside `issues.yaml` in the state root and
moves nowhere when epics move between `planned/`, `active/`, and `archived/`.

### Four separable components

Each component learns per metric. `scope`, `closure`, and `orchestration` each **activate
independently per metric** at **≥3 samples**. `fix` is stricter — see "The `fix` cohorts"
below.

| Component | Learns | Sampled at |
|---|---|---|
| `scope` | story sizing ratio, per classification | inside `set-actual --node story` |
| `closure` | closure overhead ratio, separately for sprint and epic level | inside `set-actual --node sprint\|epic` |
| `fix` | fix cost, per classification (`clean` vs `reworked` cohorts) | inside `set-actual --node story` |
| `orchestration` | orchestration overhead as a **fraction** of children's actuals, separately for sprint and epic level | inside `set-actual --block orchestration --node sprint\|epic` |

`CALIBRATED_METRIC_FIELDS` is `METRIC_FIELDS` minus `cost` — `("elapsed_hours", "man_hours",
"hitl_hours", "tokens_k")`. `cost` never calibrates on any component, at any level: it is
derived from `tokens_k × rates`, so letting it also accumulate an independently-learned
correction would give a derived value its own drift, undoing exactly what deriving it was for.

Splitting the four components matters because they fail differently: `scope` drifts with
codebase familiarity, `closure` is a near-fixed per-sprint tax that a single blended ratio
hides entirely, `fix` tracks review strictness, and `orchestration` tracks how much
supervision/coordination overhead a run actually needs. A component below its activation
threshold uses its cold-start prior — ratio `1.0` for `scope`/`closure`, `F` = `1.25` for
`fix`, and **nothing** for `orchestration` — while its siblings may already be calibrated.

**`orchestration` learns a FRACTION, not a ratio — the one component that does.** Every other
component corrects an existing number: a ratio is `actual / estimate`-shaped, dividing out
what was already applied. Orchestration has no such number to correct: its band ships
unseeded by design, because the only overhead measurements available when this was built were
contaminated by an operational defect (roughly thirty blocking waits that each outlived the
prompt cache and re-created a ~93k-token prefix), and sizing a cold-start prior on that data
would have committed the bug to every future estimate. So the sample **is** the band:
`orchestration_actual / Σ children's actual`, for a given metric, directly observable from the
first closed sprint or epic that carries an `orchestration` block. This is why
`active_orchestration_fraction` returns `None` (not a cold-start value) below `MIN_SAMPLES` —
there is nothing to fall back to.

### Sample weighting

`scope`, `closure`, and `orchestration` samples are **exponentially decay-weighted with decay
0.8** (`weighted_ratio`) — the most recent sample carries weight 1, the one before it 0.8, then
0.64, and so on. Recent work is a better predictor than early-project work, and the decay
lets ratios (or, for orchestration, fractions) track a changing codebase or process without
any explicit window or manual reset.

`fix` does **not** use decay weighting — each cohort (`clean`/`reworked`) keeps a running
**mean**, updated in place (`_bump_cohort`), not a sample list. See "The `fix` cohorts"
below.

### Token samples and the observed mix

`tokens_k` ratios accumulate **only from runs with real actuals** — the guard is generic
(`_num_or_none` rejects `N/A`/non-numeric), so it applies on every runtime, but in practice
only Claude runs supply real token values. An `N/A` or missing value is skipped entirely for
that metric, never imputed, never counted toward the ≥3 activation threshold — the other
calibrated metrics on the same story still record. A project run mostly on other runtimes
therefore keeps calibrated `man_hours`, `hitl_hours`, and `elapsed_hours` while `tokens_k`
legitimately stays at cold-start.

Separately, `record_story_sample` also appends to `cal["token_mix"]["samples"]` whenever a
story's actual `tokens_k` mapping has a positive total — the observed per-class split as a
fraction of that total. This is **not** a calibration component (§6): it feeds `observed_mix`,
which supplies the class split used to price `cost` at estimate time, once ≥3 usable samples
exist; below that, `COLD_START_TOKEN_MIX` (an assumption, not a measurement) is used instead.

### The scope/fix split — iteration-based, with back-out as fallback

Approach A alone (dividing the actual by the *assumed* `fix_factor` to recover a scope
figure) is circular for a `fix` sample: it divides by the very number it is trying to learn,
so `fix` could only ever re-derive its own prior. `derive_story_sample` avoids this for the
`fix` side by using `completion_evidence.fix_iterations` directly:

**The sample must be measured against the BASE BAND, not against the last estimate.** The
estimate is `band_mid × scope_ratio_applied × fix_factor`, so a raw `actual / estimate`
measures error against an estimate that already contains the previous ratio. Feeding that
back as the next ratio makes the loop converge to `√(truth ÷ band_mid)` — a permanent
underestimate that no volume of data closes — and means a perfect estimate never produces a
neutral sample. `derive_story_sample` therefore divides the applied ratio back out, per
calibrated metric, using `estimate.scope_ratios[metric]` (falling back to a scalar
`scope_ratio`, then to `1.0`).

**The two paths differ arithmetically**, which is what makes approach A a real back-out
rather than a relabelling:

- **`fix_iterations == 0`** (and a `fix_factor` is present) — the story needed no rework, so
  the actual is pure scope. `provenance: exact`:

  ```
  sample = actual × scope_ratio_applied × fix_factor / estimate     ( = actual / band_mid )
  ```

  Man-hours also feed the `clean` cohort of `fix` unmodified.

- **`fix_iterations > 0`, or the field is absent entirely** (a `fix_factor` is present, but
  the completion evidence doesn't say zero) — the actual mixes scope and rework, so the
  scope portion is `actual ÷ fix_factor` and the fix factor **cancels**.
  `provenance: backout`:

  ```
  sample = actual × scope_ratio_applied / estimate     ( = actual / (band_mid × fix_factor) )
  ```

  When `fix_iterations` is a real number `> 0`, man-hours also feed the `reworked` cohort;
  when the field is simply **absent**, no fix-cohort sample is recorded — there's a fix
  factor to back out arithmetically, but no iteration count to say which cohort the
  man-hours belong to.

- **The estimate has no `fix_factor` recorded at all** (a story estimated before
  `estimate-story` existed, or estimated by hand) — `provenance: legacy`, checked first and
  independent of `fix_iterations`. Both missing factors are treated as `1.0`, so the sample
  is `actual / estimate`; the label preserves the imprecision for a later audit. No
  fix-cohort sample is recorded: there is nothing to attribute rework to without knowing
  what fix multiplier, if any, was baked into the estimate.

A consequence worth stating plainly: on the `exact` path a story that consumes its entire
fix reserve without any rework produces a sample of `ratio × fix_factor`, because that
really is evidence that scope was under-modelled by the reserve. On the `backout` path,
`actual == estimate` produces exactly the ratio that was applied — a neutral sample.

**Because `man_hours`'s definition changed, its `clean`/`reworked` cohort mean is now a mean
of counterfactual re-assessments, not observed effort.** The mechanics above are unaffected —
`_bump_cohort` still accumulates whatever `actual.man_hours` says — but a project migrating
from before this rework must not mix pre- and post-rework `man_hours` samples in the same
cohort mean; that is exactly what the metrics migration (below) quarantines.

**`fix_iterations` must be on the node BEFORE `set-actual` runs.** The sample is derived
inside `set-actual`, so evidence written afterwards is invisible to it:
`provenance: exact` becomes unreachable, neither `fix` cohort ever fills, and `F` = 1.25
freezes. `steps/sprint/step-03-dev-loop.md` §4 writes the completion evidence first for
exactly this reason.

`derive_story_sample` returns `None` — no sample at all — when the node has no `estimate` or
no `actual` block, or when every calibrated metric's estimate/actual pair is
missing/`N/A`/zero.

### Closure sampling — the residual and its denominator

```
Σ children estimate = E
closure actual      = actual(parent) − Σ actual(children)
closure expected    = midpoint(parent estimate) − E − E × orchestration_fraction_applied × mid(ORCH_SPREAD)
sample              = closure actual × closure_ratio_applied / closure expected
```

**The denominator must be the quantity the ratio is applied to.** `estimate-rollup` applies
the learned ratio to the closure band alone (`total × (1 + ratio × closure band + fraction ×
ORCH_SPREAD)`), so dividing the residual by the *whole* parent estimate midpoint measures a
different quantity than the one being corrected and the loop cannot converge — with a
perfectly consistent history it moved the roll-up *away* from the observed total. And,
exactly as with `scope`, the estimated overhead already contains the ratio that was applied
when the parent estimate was written (`estimate.closure_ratios[metric]`, `1.0` when absent),
so that ratio is divided back out.

**The orchestration band is subtracted off before dividing, for the same reason.** Since
orchestration joined the roll-up, `midpoint − Σ children estimate` is the closure band **plus**
the orchestration band — while the residual it divides is closure-only, because orchestration
is a separate block outside `actual` (see "Attribution" in §6). Leaving it in the denominator
understates every closure sample by exactly the factor the two bands differ by: with children
summing to 20, an active orchestration fraction of `0.5`, and a true closure overhead of `5`,
the recorded sample is `0.3704` instead of the correct `1.4286` — 3.9× low, and worse as the
fraction grows. `derive_closure_sample` therefore subtracts `Σ children estimate ×
estimate.orchestration_ratios[metric] × mid(ORCH_SPREAD)` (`ORCH_MID`, `1.0` for the shipped
`(0.8, 1.2)`) before dividing, leaving exactly the closure band.

Worked, with orchestration inactive: four children estimated 10 each (Σ 40), true closure
overhead 8 every time, true total 48. Cold start rolls up to `40 × (1 + 1.0 × 0.175) = 47`,
expected overhead 7, sample `8 × 1.0 / 7 = 1.143`. Once active, `40 × (1 + 1.143 × 0.175) =
48.0` — the observed total — and every later generation samples `8 × 1.143 / 8 = 1.143` again,
so the ratio holds.

Worked, with orchestration **active** at fraction `0.5`: two children estimated 10 each (Σ 20),
true closure overhead 5. The roll-up is `20 × (1 + 1.0 × 0.10 + 0.5 × 0.8) = 30` to
`20 × (1 + 1.0 × 0.25 + 0.5 × 1.2) = 37`, midpoint `33.5`. Expected closure overhead is
`33.5 − 20 − 20 × 0.5 × 1.0 = 3.5`, so the sample is `5 × 1.0 / 3.5 = 1.4286`. Feeding it
back: `20 × (1 + 1.4286 × 0.10 + 0.4) = 30.857` to `20 × (1 + 1.4286 × 0.25 + 0.6) = 39.143`,
midpoint `35.0`, expected overhead `35.0 − 20 − 10 = 5.0`, and the next sample is
`5 × 1.4286 / 5 = 1.4286` — stable, and the midpoint now reconciles as
children `20` + closure `5` + orchestration `10`.

Closure sampling skips **per metric, with a reason**, never aborting the other metrics'
samples: a child missing that metric's actual or estimate (a partial sum understates
overhead, permanently, since a low ratio has no marker saying it was incomplete); an
estimated closure overhead of `≤ 0` (nothing to measure the residual against); a negative
residual (a miscount — except for `elapsed_hours`, where a negative residual is *expected*
if children ever overlap in wall-clock time; today's step files run children strictly in
order, so this is defensive, not currently reachable); a **zero** residual; and an `N/A`
`tokens_k` on either side. Only when *no* calibrated metric produces a residual is the whole
sample skipped.

**A zero residual is a skip, not a sample of `0.0`.** "Zero" here means *within a relative
tolerance, on either sign* — not exactly `0.0`: the residual is unrounded float arithmetic, so
a bare sum over ordinary decimals lands just off zero in one direction or the other
(`0.3 + 0.6` against `0.9` leaves `+1.11e-16`; `1.1 + 2.2` against `3.3` leaves `-4.44e-16`),
and an exact comparison would catch neither. Both signs give the same skip reason, so the
negative case is not mis-reported as a miscount. A parent actual equal to the sum of its
children means this level's own closure-phase spend was attributed to nothing (see
"Attribution" in §6). Recording that as a legitimate `0.0` is strictly worse than recording
nothing: `0.0` is not `None`, so after three such closes `active_closure_ratio` returns `0.0`,
`estimate-rollup` accepts it, and the closure band contributes nothing to any future estimate
— permanently, with nothing on disk saying why. The skip reason names the defect and points
back at the capture rule.

A stored sample of `0.0` is ignored on read — excluded from the weighted average and
from the count toward the three-sample activation threshold. The write-side guard in
`derive_closure_sample` refuses to create one; this is what protects a file that already
contains one, which no migration can be relied on to reach.

### The orchestration sample — denominator completeness

```
sample(metric) = orchestration.actual(metric) / Σ children's actual(metric)
```

recorded only when **every** child has a numeric actual for that metric — a partial sum would
silently understate the true total and inflate the fraction, permanently and invisibly. This
is the same completeness guard `derive_closure_sample` applies to its residual, reused here
rather than duplicated. `cost` is not sampled (it is outside `CALIBRATED_METRIC_FIELDS`); its
fraction is already implied by the `tokens_k` fraction, and a second, independently-drifting
copy would add nothing but disagreement.

### Idempotency

`set-actual` stamps `calibration_sampled_at` on the node once it has emitted that node's
`actual`-block sample, and a separate `orchestration_sampled_at` once it has emitted the
`orchestration`-block sample — **two markers on one node**, deliberately independent: a
sprint or epic node carries both an `actual` and an `orchestration` block, and one marker
would let whichever write happens first silently suppress the other. A second `set-actual`
on the same block records nothing and says so in its stdout suffix (`sample already recorded
at … — skipped (replay)`). `--no-calibrate` still exists for backfills, but correctness no
longer depends on the caller remembering it.

### Concurrency

`pm-calibration.yaml` is a shared append target — every `set-actual`, across every parallel
subagent, may append to it. The **whole load → mutate → save cycle** runs under one
exclusive `flock` (`calibration_lock`), not just the save: locking only the save let two
concurrent samplers read the same pre-append state and the second one silently drop the
first's sample. At the default `max_parallel_subagents = 4` that lost roughly half of all
samples, with every call still exiting 0.

### The `fix` cohorts

`fix` does not store a ratio per sample. It keeps two running means per classification,
`clean` and `reworked` — man-hours for stories that needed no fix iteration vs. stories that
needed at least one — and derives `avg_fix_factor = reworked.mean_man_hours /
clean.mean_man_hours` on read.

**Activation requires BOTH cohorts to reach ≥3 samples**, not just one (`active_fix_factor`).
One cohort alone cannot form a ratio — a mean of `reworked` man-hours means nothing without a
comparable `clean` mean to divide by, and vice versa. This is why a project where every story
needs rework never activates `fix`, no matter how many `reworked` samples pile up: it has no
`clean` baseline to compare against, and `F` = 1.25 remains the correct number to keep
using — the asymmetry (unlike `scope`/`closure`/`orchestration`, which activate on a single
count) is deliberate, not a bug.

### Granularity

`granularity` lives **in the calibration file itself** (`new_calibration`'s `granularity`
key), not bound from a step file or `customize.toml` — nothing currently varies it, so every
project effectively runs `"story"` granularity: `set-actual --node story` records one scope
sample and (when derivable) one fix-cohort update per closed story; `set-actual --node
sprint|epic` records one closure sample per closed sprint/epic, unconditionally, and
`set-actual --block orchestration --node sprint|epic` records one orchestration sample per
closed sprint/epic that carries an `orchestration` block. There is no `"sprint"`-granularity
aggregation path in the shipped code — a project cannot presently opt into coarser story
sampling by changing this key. `calibration show` prints whatever value is stored for
information only; it does not change any sampling behavior.

### Schema

```yaml
version: 2
granularity: story
metrics_migrated_at: '2026-08-18T09:00:00Z'   # present once the metrics migration (below) has run
scope:
  simple:   { man_hours: {samples: [1.02, 1.14, 0.98]}, hitl_hours: {...}, elapsed_hours: {...}, tokens_k: {...} }
  standard: { ... }
  complex:  { ... }
closure:
  sprint:   { man_hours: {samples: [1.18, 1.05, 1.22, 0.97]}, ... }
  epic:     { ... }
orchestration:                                  # per level x per calibrated metric; FRACTION samples
  sprint:   { man_hours: {samples: [0.08, 0.11, 0.09]}, hitl_hours: {...}, elapsed_hours: {...}, tokens_k: {...} }
  epic:     { ... }
fix:
  simple:   { clean: {mean_man_hours: 3.1, samples: 4}, reworked: {mean_man_hours: 4.2, samples: 3} }
  standard: { ... }
  complex:  { ... }
token_mix:                                      # derived statistic, not a calibration component
  samples:
  - { input: 0.14, output: 0.06, cache_write: 0.29, cache_read: 0.51 }
legacy:                                          # quarantined pre-rework man_hours/fix samples
  fix: { ... }                                  # never read again by any active path
```

`scope`, `closure`, and `orchestration` entries store the **raw sample list** (`samples:
[...]`, newest last) — the weighted mean (a ratio for `scope`/`closure`, a fraction for
`orchestration`) is computed on read by `weighted_ratio`, never persisted. `fix` entries store
a running **mean and an integer count** per cohort — `avg_fix_factor` is not a file field; it
is `active_fix_factor(cal, classification)`, computed on read from the two cohort means, and
only returned once both cohorts clear `MIN_SAMPLES`.

A `scope` ratio is `actual / band_mid` (or `actual / (band_mid × fix_factor)` on the backout
path), a `closure` ratio is `closure actual / closure expected`, and an `orchestration` sample
is `orchestration_actual / Σ children_actual` — the first two divide the applied ratio back
out per "The scope/fix split" and "Closure sampling" above; orchestration has no prior ratio
to divide out, since it is not correcting anything (see "Four separable components"). A
component below its activation threshold is recorded but **not applied** — `estimate-story`
and `estimate-rollup` fall back to the cold-start prior for that metric/bucket (or, for
orchestration, to contributing nothing).

### The metrics migration (`calibration migrate-metrics`)

A calibration file written **before this metrics rework** — even one already at
`version: 2` under the older four-metric schema — needs reshaping, not just a version bump,
because the metric set itself changed. `migrate_calibration_metrics` does this in place:

- **`cost` samples are dropped**, from every `scope`/`closure`/`orchestration` bucket that has
  one. `cost` is derived now and never independently calibrated again (§2, §6).
- **The old wall-clock samples are renamed to the `elapsed_hours` key**, in every bucket,
  matching the estimate side's field-name unification (§2).
- **`man_hours` samples, and the whole `fix` block, are quarantined under `legacy`** —
  `legacy.<component>.<bucket>.man_hours` for scope/closure, `legacy.fix` wholesale. The
  metric's definition changed from observed human attention to counterfactual developer
  effort, so old samples measure a different quantity and are not comparable; they are kept
  for audit, never read by any active calibration path again.
- **A `tokens_k` weighted ratio outside `TOKENS_SANITY_RANGE = (0.5, 2.0)` is flagged, not
  dropped** — carried forward as-is, with a log line suggesting it may be contaminated by
  orchestration-shaped overhead that leaked into story samples under the old rules (exactly
  the defect `orchestration` now isolates into its own component).
- **`token_mix` is seeded empty by this migration** — but only when this pass actually found
  and moved legacy content (`if log and "token_mix" not in cal`), not unconditionally: seeding
  it on a brand-new project's first, no-op pass would recreate a conflict this design
  deliberately avoids. **`orchestration` is a separate case, seeded by a different mechanism**:
  `new_calibration` always includes an empty `orchestration` key on a fresh file, and
  `load_calibration` backfills it on every load of an older file that lacks one
  (`for key, default in (("scope", ...), ..., ("orchestration", CLOSURE_LEVELS)): if key not
  in data: data[key] = ...`) — unconditionally, independent of whether
  `migrate_calibration_metrics` finds anything to migrate. `migrate_calibration_metrics`
  itself never seeds `orchestration` at all.

This runs **once**, gated on `CALIBRATION_METRICS_MARKER = "metrics_migrated_at"` — a
positive marker stamped at the end of every real pass, **even a no-op one** on a brand-new
project, so a later legitimate `man_hours`/`fix` sample is never revisited and wrongly
quarantined. Once past the gate, `man_hours` and `fix` quarantine **unconditionally** — no
corroborating `cost` sample, or old wall-clock sample, is required in the same bucket, because a
non-Claude-runtime project may never have accumulated `cost`/token samples at all, and
requiring one would leave old-definition `man_hours` silently uncaught. This is **not** a
`version` bump — the schema version stays `2` throughout; `metrics_migrated_at` records a
reshape of the file, not a new schema generation (the same way `orchestration`, `token_mix`,
and `legacy` are data about the file, not schema versions).

The file is preserved beforehand as `pm-calibration.yaml.pre-metrics` (parallel to
`pm-calibration.yaml.v1` for the older version-1-to-2 migration below), and the migration is
idempotent — a second run is a no-op because the marker is already set.

Both `record_story_sample` and `record_closure_sample` (and `record_orchestration_sample`) run
this migration automatically, inline, before appending a new sample — so it happens
transparently the first time any project touches its calibration file after upgrading. It is
also exposed directly:

```bash
python3 {pm_status} calibration migrate-metrics --state-root {pm_state_root} [--format {text,json}]
```

**Never runs from a read-only command.** `calibration show`, `estimate-story`, and
`estimate-rollup` only read the file (`load_calibration`) and never migrate it — a
never-migrated file just reads as "nothing sampled yet" for `man_hours`/`fix`/`orchestration`
until a write path actually runs.

### `version: 1` migration

Distinct from the metrics migration above — this is the older schema-shape migration, still
present and unaffected by this rework. A `version: 1` file is auto-migrated **the first time a
write path touches it** (`record_story_sample` / `record_closure_sample`, both via
`migrate_calibration`). The original is preserved alongside as `pm-calibration.yaml.v1` and is
never read again. Migration maps the old blended ratio onto the `scope` component and starts
`closure`, `fix`, and `orchestration` fresh at zero samples — the old file has no way to
separate them, and seeding them from a blended figure would import exactly the bias the split
exists to remove.

**`load_calibration` never migrates**, either version-1-to-2 or the metrics reshape above. It
is deliberately side-effect-free: `calibration show` and `estimate-story`/`estimate-rollup`
(which only read the file to look up active ratios) call `load_calibration` and treat an
unmigrated file as if the missing components had no samples yet, but they never rewrite it.
Only the sampling write paths migrate, and only at the moment they are about to append.

> The `version:` key is the **calibration file's schema-shape version** (1 vs. 2 — the
> component structure: scope/closure/fix, later joined by orchestration/token_mix/legacy). It
> is unrelated to state *layout* generations ("sharded", "legacy per-epic", "legacy flat") and
> unrelated to `metrics_migrated_at`, which tracks a content reshape within version 2.

### Mechanization status

`pm-status.py` now runs this loop; it is not orchestrator prose.

- **`estimate-story`** and **`estimate-rollup`** read the file (`load_calibration`, never
  migrating) and apply whichever ratios/fractions are active — cold-start priors (or, for
  orchestration, nothing) otherwise.
- **`set-actual`** derives and appends a sample automatically after every successful actuals
  write (`record_story_sample` for `--node story`; `record_closure_sample` for `--node
  sprint|epic` on the `actual` block; `record_orchestration_sample` for the `orchestration`
  block), unless `--no-calibrate` is passed. A derivation failure is caught, warned on
  stderr, and never fails the actuals write — the actual is the primary record; the
  calibration sample is derived, secondary data. The `set-actual` stdout line reports what
  was recorded (e.g. `scope+4 metrics, provenance=exact, class=complex`, or `orchestration
  sprint +3 metrics`) or why nothing was (e.g. `no sample (missing estimate or actual)`).
  **Skip reasons go to stdout**, inside that `[...]` suffix — only an unexpected exception
  warns on stderr.
- **`calibration show`** is read-only. A missing file reports cold-start for every component
  and exits `0` — there is no error state for "no calibration data yet."
- **`calibration migrate-metrics`** performs the one-time reshape described above and reports
  a change log; also run automatically, inline, by the two sampling write paths.

See §9 for the disagreements this closes and the ones that remain open.
