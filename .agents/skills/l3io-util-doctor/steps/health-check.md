## Project Health Check

The default mode — runs when no recognized keyword is passed, or when `check`/`status` is passed. Scans the project and reports what needs attention in a structured table. When not in read-only mode (`check`/`status`), proposes the ordered set of actions and executes them after a single confirmation.

### Step HC1 — Load config

Load config same as described above under On Activation.

### Step HC2 — Scan (12 checks, read-only)

Run all checks. No files are changed at this step.

**Check 1 — Status file naming**
Does `{implementation_artifacts}/sprint-status-active.yaml` exist?
- Yes → flag `rename-active` · Priority: Critical (must run before any other status-file action)
- No → ✓

**Check 2 — Status file layout**
Do `sprint-status-backlog.yaml` OR `sprint-status-archived.yaml` exist in `{implementation_artifacts}/`?
- Neither exists, but `sprint-status.yaml` is present with content that includes done or backlog epics → flag `split-status` · Priority: High
- Neither exists and no `sprint-status.yaml` → new project, no status-file action needed
- At least one split file exists → split layout in use, ✓

**Check 2b — State layout migration**
Count which of the three state layouts are present: sharded (`{pm_state_root}` i.e.
`{implementation_artifacts}/state/` exists), legacy per-epic (`{project-root}/_bmad/state/`
exists), legacy flat (`sprint-status*.yaml` exists in `{implementation_artifacts}/`).
- Only sharded present, or none present (new project) → ✓
- Exactly one legacy layout present, sharded absent → flag `migrate-state` · Priority: High
  (runs after `split-status` if both are flagged)
- More than one layout present → flag `migrate-state` · Priority: Critical — an interrupted
  migration left state in two places; do not run any other action until this is resolved

**Check 3 — Status file schema**
For each present status file, spot-check the first epic node and first sprint node for missing required fields (the full field list is in Schema Migration Mode Step M2). If any required field is absent, the full `migrate-schema` analysis is needed.
- Gaps detected → flag `migrate-schema` · Priority: Medium (run before `split-status` if both are needed)
- No gaps → ✓

**Check 4 — Artifact layout**
Scan the top level of `{implementation_artifacts}` and `{planning_artifacts}` for flat classifiable files (story files matching heuristic 1, sprint/epic closure files matching heuristics 2–3, test files matching heuristic 4, misplaced planning docs matching heuristic 5 — all from `steps/layout-cleanup.md` (File Classification Heuristics)).
- Flat classifiable files found → flag `layout-cleanup` · Priority: Medium · note count
- None → ✓

**Check 5 — State file naming**
If `{pm_state_root}` exists, run the naming validation from Sort Status Mode Step SO2 over it.
- Misnamed entries found → flag `sort-status` · Priority: Low
- No `{pm_state_root}` yet, or all names valid → ✓

**Check 6 — Deferred code markers**
Run the `bmad-defer:` grep from Harvest Debt Mode (Step H2 grep command). Dedupe against the existing `backlog:` list (Step H3 logic). Count new (unharvested) markers.
- New markers found → flag `harvest-debt` · Priority: Low · note count
- None or all already harvested → ✓

**Check 7 — AI instruction references**
Run the scan from Update AI Rules Mode Step AR1 across all well-known instruction file locations.
- Stale legacy state references found (flat `sprint-status*.yaml`, the three-file split, or `_bmad/state/`) → flag `update-ai-rules` · Priority: Low · list files
- All current or absent → ✓

**Check 8 — Status file placement and backlog structure**
Only runs if the split layout is present. Parse all three split files and check:
1. Any epic whose placement file does not match its `status` (e.g., `status: done` in `sprint-status.yaml`)?
2. Any nested per-epic `backlog:` arrays inside `epics[N].backlog:` in any of the three files (should be in the flat top-level `backlog:` list only)?
3. Any items in the top-level `backlog:` list with `status` other than `backlog` (stale resolved/promoted items)?
4. Any epic shells in `sprint-status-backlog.yaml` with an empty or absent `sprints:` list where that epic is already in-progress in `sprint-status.yaml` (empty shells with no remaining backlog sprints)?
- Any issue found → flag `reconcile-status` · Priority: High · note count per category
- Split layout absent → skip (not applicable until after `split-status`)
- No issues → ✓

**Check 9 — Migration backup files**
Scan `{implementation_artifacts}/` for `*.yaml.legacy` files (e.g., `sprint-status.yaml.legacy`); `{project-root}/_bmad/` for `*.yaml.v1` calibration backups (e.g., `pm-calibration.yaml.v1`) and for `pm-calibration.yaml.legacy`; and `{project-root}/_bmad/` for the `state.legacy/` and `migration-backup/` backup directories left by `migrate-state` (see Clean Legacy Mode's Step CL1 for exactly what each holds).
- Any found → flag `clean-legacy` · Priority: Low · note count (files and directories separately)
- None → ✓

**Check 10 — Epic directory padding (legacy two-digit form)**
Scan the top level of `{implementation_artifacts}/` for directories matching `epic-[0-9][0-9]`
(exactly two digits).
- Any found → flag `rename-epic-dirs` · Priority: **High** · list directories — state path
  resolution (`epic-{nnn}` under `state/`) and the state/artifact mirror both depend on the
  three-digit form; a two-digit `epic-{nn}/` will never match its `state/{status}/epic-{nnn}/`
  counterpart or be found by Check 11's drift diff.
- None → ✓

**Check 11 — State/artifact drift**
`{pm_state_root}` = `{implementation_artifacts}/state` (see `references/status-files.md`,
the canonical state-layout contract, for the full sharded schema this check reads). For each
sprint directory under `{pm_state_root}/{planned,active,archived}/epic-{nnn}/sprint-{nn}/`,
compare story state files against story artifacts by basename. Only `active/` and `archived/` are
checked — a `planned/` epic legitimately has state and no artifacts yet (stories are authored after
planning), so that asymmetry is not drift:

```bash
diff <(ls {pm_state_root}/{active,archived}/epic-{nnn}/sprint-{nn}/*.yaml 2>/dev/null \
        | xargs -n1 basename | sed 's/.yaml//' | grep -v '^sprint$') \
     <(ls {implementation_artifacts}/epic-{nnn}/sprint-{nn}/stories/*.md 2>/dev/null \
        | xargs -n1 basename | sed 's/.md//')
```

Lines starting `<` are state files with no story artifact; lines starting `>` are story
artifacts with no state. Also flag any story or sprint file whose `epic:`/`sprint:`
back-reference disagrees with the directory it was found in.
- Any mismatch found → flag for report · Priority: **Medium** · list the orphaned keys —
  report only, **never auto-correct**: an orphan on either side needs a human decision about
  which side is right (a dropped story file vs. an abandoned state node look identical from
  the diff alone).
- None → ✓

**Check 12 — Poisoned calibration provenance**
A fixed defect: an older `set-field` stored `completion_evidence.fix_iterations` as a
**string**, and `derive_story_sample` (the function behind `set-actual`'s live sampling and
Redrive Mode's rebuild) reads that field to decide a sample's provenance. A story that needed
no rework compared its string `'0'` against the int `0` and derived as `backout` instead of
`exact`, silently corrupting its `scope` ratio. `pm-calibration.yaml` cannot be read to detect
this — it stores bare rounded ratios with no provenance recorded — so this check reads the
nodes themselves, which still hold the original field. `NUMERIC_NODE_FIELDS` now coerces this
field on every write, so a string can only have been written by a version that predates that
fix; its presence means this project generated samples under the defect.

If `{pm_state_root}` exists, scan every story node file under
`{pm_state_root}/{active,planned,archived}/epic-*/sprint-*/E*.yaml` and check whether
`completion_evidence.fix_iterations` is a string (as opposed to absent, or an integer):

```bash
uv run --with ruamel.yaml python3 - "{pm_state_root}" <<'PY'
import sys
from pathlib import Path
from ruamel.yaml import YAML

yaml = YAML(typ="safe")
state_root = Path(sys.argv[1])
hits = []
for status in ("active", "planned", "archived"):
    base = state_root / status
    if not base.is_dir():
        continue
    for story_file in sorted(base.glob("epic-*/sprint-*/E*.yaml")):
        node = yaml.load(story_file.read_text()) or {}
        val = (node.get("completion_evidence") or {}).get("fix_iterations")
        if isinstance(val, str):
            hits.append(str(story_file))
for h in hits:
    print(h)
print(f"TOTAL {len(hits)}")
PY
```
- Any story with a string `fix_iterations` found → flag `redrive` · Priority: **Medium** ·
  note count — same class as Check 11 (State/artifact drift): silent corruption of trusted
  state that never blocks execution, but poisons downstream `estimate-story`/`estimate-rollup`
  output for as long as it goes unrepaired.
- No `{pm_state_root}` yet, or none found → ✓

### Step HC3 — Report findings

Print the health check table. Use ✓ for passing checks, ⚠ for flagged items:

```
PROJECT HEALTH CHECK — {implementation_artifacts}
================================================================
Check                           Status                         Action
----------------------------------------------------------------
Status file naming              ⚠ sprint-status-active.yaml    rename-active
Status file layout              ✓ Split layout in use          —
Status file schema              ✓ All fields current           —
Status placement & backlog      ⚠ 1 misplaced epic, 3 nested  reconcile-status
Artifact layout                 ⚠ 3 flat file(s) detected     layout-cleanup
Status file ordering            ✓ All sorted                   —
Deferred code markers           ⚠ 2 new marker(s)             harvest-debt
AI instruction references       ✓ Current                      —
Migration backup files          ⚠ 1 .legacy file found         clean-legacy
Epic directory padding          ⚠ 1 legacy epic-{nn}/ dir       rename-epic-dirs
State/artifact drift            ⚠ 2 orphaned key(s)             — (report only)
Calibration provenance           ⚠ 4 poisoned sample(s)         redrive
================================================================
```

If flagged items exist, append the recommended execution sequence (only flagged actions shown, in priority order):
```
Recommended actions (in order): rename-active → rename-epic-dirs → split-status → migrate-state → layout-cleanup → harvest-debt
```

Never emit a sequence that includes a legacy-only action (`migrate-schema`, `split-status`,
`reconcile-status`) but omits `migrate-state`. Those modes only exist to prepare a legacy tree
for migration, so if one of them is flagged the project is on a legacy layout and
`migrate-state` is flagged too. A sequence ending before `migrate-state` would leave the
project in a shape the PM skills cannot read while reporting success.

If nothing is flagged:
```
✓ Project is healthy — no actions needed.
```

### Step HC4 — Exit if read-only

If invoked with `check` or `status`: print the report above and exit. No further steps.

### Step HC5 — Propose and confirm

If no items are flagged: print "✓ Nothing to do." and exit.

Otherwise ask:
```
Run {N} recommended action(s) in sequence?
  Y — run all ({action_list})
  n — exit, no changes
```

If `n`: print "Exiting — no changes made." and exit.

### Step HC6 — Execute in order

Run each approved action in this fixed priority sequence (skip any that were not flagged):

1. `rename-active`
2. `rename-epic-dirs`
3. `migrate-schema`
4. `split-status`
5. `migrate-state`
6. `reconcile-status`
7. `layout-cleanup`
8. `sort-status`
9. `harvest-debt`
10. `update-ai-rules`
11. `redrive`
12. `clean-legacy`

`redrive` must run after `migrate-state` — it walks the sharded state tree, which does not
exist before that step — and after every other action that can add, move, or rewrite node
files (`reconcile-status`, `layout-cleanup`, `sort-status`), so it rebuilds calibration
samples from the most fully-corrected tree available. It runs before `clean-legacy` only
because that step is the fixed final tidy-up; nothing about `redrive` depends on backup files
still being present.

Before each action, print a separator header:
```
─── Running: {action-name} ──────────────────────────────────
```

Each action runs its full mode implementation from its own section. **Suppress the per-mode confirmation prompts** — the user already confirmed in HC5; proceed as if they answered yes at each mode's own confirm step. The per-mode dry-run output and verify steps still run and are shown.

If any action fails (exits with FAILED), stop and report — do not run remaining actions.

**State/artifact drift (Check 11) is report-only** — it never appears in this execution list.
It has no fixer action; its findings surface in Step HC3's table for the user to resolve by
hand (author the missing story, or clean up the orphaned state node).

### Step HC7 — Final summary

```
HEALTH CHECK COMPLETE
================================================================
  Ran:     {comma-separated list with ✓ or ✗ per action}
  Clean:   {comma-separated list of checks that passed with ✓}
================================================================
{overall status line}
```

If all actions succeeded: "Project is now healthy."
If any action failed: "One or more actions failed — see output above for details."

---
