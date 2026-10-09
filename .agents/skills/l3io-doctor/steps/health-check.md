## Project Health Check

The default mode — runs when no recognized keyword is passed, or when `check`/`status` is passed. Scans the project and reports what needs attention in a structured table. When not in read-only mode (`check`/`status`), proposes the ordered set of actions and executes them after a single confirmation.

### Step HC1 — Load config

Load config same as described above under On Activation.

### Step HC2 — Scan (26 checks, read-only)

Run all checks. They change no project files, with one exception: a check that runs
`pm-status.py` (Check 13) takes its locks when an issue file exists, and taking a lock may
create that lock file and `{pm_state_root}/.gitignore` (the `*.lock` rule `pm-status.py`
maintains). Checks 15–19 run `{spec_align}` in its read-only modes, which write nothing.

**Check 1 — Status file naming**
Does `{implementation_artifacts}/sprint-status-active.yaml` exist?
- Yes → flag `rename-active` · Priority: Critical (must run before any other status-file action)
- No → ✓

`rename-active` is an **inline action with no mode file** — Step HC6 performs it. It is a
single rename of a legacy flat file, so it can only fire on a project that still has
`sprint-status-active.yaml`; there is nothing for it to do on a migrated one, and it had no
caller outside this check.

**Check 2 — Status file layout**
Do `sprint-status-backlog.yaml` OR `sprint-status-archived.yaml` exist in `{implementation_artifacts}/`?
- Neither exists, but `sprint-status.yaml` is present with content that includes done or backlog epics → flag `split-status` · Priority: High
- Neither exists and no `sprint-status.yaml` → new project, no status-file action needed
- At least one split file exists → split layout in use, ✓

**Check 2b — State layout migration**
Count which of the three state layouts are present: sharded (`{pm_state_root}` i.e.
`{implementation_artifacts}/state/` exists), legacy per-epic (`{project-root}/_bmad/state/`
exists), legacy flat (`sprint-status*.yaml` exists in `{implementation_artifacts}/`).

The flat-plus-sharded pair specifically — `bmad-build` writes the flat file only when it
already exists (bmm's `step-03-implement.md:27`), while this package's PM skills read and
write the sharded tree under the same artifact root — is a deterministic, unit-tested
predicate rather than a judgment call, so check it with the script first, before falling back
to the general three-layout count below for every other combination:

```bash
uv run {skill-root}/scripts/detect-layout.py --artifacts {implementation_artifacts}
```

- Exit 1 (prints `layout-collision: both <flat> and <sharded>/ exist`) → flag `migrate-state` ·
  Priority: **Critical** — do not run any other action until this is resolved · remedy:
  > Both layouts are present. `bmad-build` writes `sprint-status.yaml` only when it already
  > exists (`step-03-implement.md:27`), so deleting or migrating the flat file stops the second
  > writer. Run `migrate-state` — it preserves the original as `sprint-status.yaml.legacy`,
  > which is not matched by that existence gate.
  Stop here — this pair alone already puts the check at its ceiling severity.
- Exit 0 → the flat file and the sharded tree are not both present (this also covers the
  post-`migrate-state` case, where the flat file has been renamed to `sprint-status.yaml.legacy`
  and so no longer matches). Continue to the general count, which still catches the legacy
  per-epic layout overlapping with either of the other two:
  - Only sharded present, or none present (new project) → ✓
  - Exactly one legacy layout present, sharded absent → flag `migrate-state` · Priority: High
    (runs after `split-status` if both are flagged)
  - More than one layout present (legacy per-epic alongside the sharded tree, or alongside the
    flat file — the flat-plus-sharded pair was already ruled out above) → flag `migrate-state`
    · Priority: Critical — an interrupted migration left state in two places; do not run any
    other action until this is resolved

This Critical, multi-layout condition is duplicated (severity and outcome, not the
flat-plus-sharded script check above) in `steps/stats.md` Step ST1, which BLOCKs rather than
walking the tree when it fires — `stats` is a read-only single mode with no findings table to
report into, so it has its own copy rather than loading this file. Keep both in sync if the
condition or severity changes.

**Check 2c — Artifact-only stories (no state YAML)**
If `{pm_state_root}` exists (sharded layout is present) or the artifact tree has story `.md`
files, scan for artifact-only stories — story `.md` files in
`{implementation_artifacts}/epic-*/sprint-*/stories/E*.md` that have no corresponding
`{story_key}.yaml` anywhere under `{pm_state_root}/{active,planned,archived}/`.

```bash
find {implementation_artifacts}/epic-*/sprint-*/stories -name 'E*.md' 2>/dev/null | sort
```

For each `.md` found, check:
```bash
find {pm_state_root}/active {pm_state_root}/planned {pm_state_root}/archived \
  -name "{story_key}.yaml" 2>/dev/null | head -1
```

- Artifact-only stories found → flag `bootstrap-state` · Priority: **High** · list the
  artifact-only story keys — these stories are invisible to `l3io-plan` and
  `l3io-execute` since those skills read state YAML, not artifact `.md` files.
- None found, or no artifact tree at all → ✓

**Check 3 — Status file schema**
For each present status file, spot-check the first epic node and first sprint node for missing required fields (the full field list is in Schema Migration Mode Step M2). If any required field is absent, the full `migrate-schema` analysis is needed.
- Gaps detected → flag `migrate-schema` · Priority: Medium (run before `split-status` if both are needed)
- No gaps → ✓

**Check 4 — Artifact layout**
Scan the top level of `{implementation_artifacts}` and `{planning_artifacts}` for flat classifiable files (story files matching heuristic 1, sprint/epic closure files matching heuristics 2–3, test files matching heuristic 4, misplaced planning docs matching heuristic 5 — all from `steps/clean-layout.md` (File Classification Heuristics)).
- Flat classifiable files found → flag `clean-layout` · Priority: Medium · note count
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
Scan `{implementation_artifacts}/` for `*.yaml.legacy` files (e.g., `sprint-status.yaml.legacy`); `{pm_state_root}/` for `*.yaml.v1` calibration backups — that is `{pm_calibration_file}.v1`, the path `pm-status.py`'s calibration v1 → v2 migration derives as `calibration_path(state_root) + ".v1"`, so it is beside the live calibration file, **not** under `{project-root}/_bmad/`; `{project-root}/_bmad/` for `pm-calibration.yaml.legacy`; and `{project-root}/_bmad/` for the `state.legacy/` and `migration-backup/` backup directories left by `migrate-state` (see Clean Legacy Mode's Step CL1 for exactly what each holds and which scan root each lives in).
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

`rename-epic-dirs` is an **inline action with no mode file** — Step HC6 performs it.

**Check 11 — State/artifact drift**
`{pm_state_root}` = `{implementation_artifacts}/state` (see `references/status-files.md`,
the canonical state-layout contract, for the full sharded schema this check reads). Enumerate
every epic in `active/` and `archived/` (a `planned/` epic legitimately has state and no
artifacts yet — stories are authored after planning, so that asymmetry is not drift), then
for each of its sprints diff the state story keys against the artifact story files:

```bash
uv run {pm_status} list-epics --state-root {pm_state_root} --format json
# → for each {key: E{nnn}, bucket} where bucket in (active, archived):
uv run {pm_status} list-stories --state-root {pm_state_root} --epic E{nnn}
# → for each sprint S{nn} the epic actually has (walk the returned keys):
state_keys=$(uv run {pm_status} list-stories --state-root {pm_state_root} --epic E{nnn} --sprint S{nn})
# Extract the canonical story-key prefix. Slug-in-filename (`E032-S01-001-centralized-file-config.md`)
# is a common human-readable convention; the state key stays canonical, the filename is UX.
# `sed 's/.md//'` alone would leave the slug attached and diff every slug-suffixed artifact as
# an orphan against its own state entry — 400+ false positives on a real project.
artifact_keys=$(ls {implementation_artifacts}/epic-{nnn}/sprint-{nn}/stories/*.md 2>/dev/null \
  | xargs -n1 basename \
  | sed -E 's/^(E[0-9]{3}-S[0-9]{2}-[0-9]{3})(-[^.]+)?\.md$/\1/' \
  | sort -u)
diff <(printf '%s\n' "$state_keys") <(printf '%s\n' "$artifact_keys")
```

`list-stories` prints one story key per line, already sorted and filtered to real story
files (`sprint.yaml`/`epic.yaml` are excluded inside the verb). Lines starting `<` are
state stories with no artifact; lines starting `>` are artifacts with no state. Also flag
any story or sprint file whose `epic:`/`sprint:` back-reference disagrees with the
directory it was found in.
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

**Check 13 — Backlog integrity and audit**
If `{pm_state_root}` exists — not gated on `{pm_issues_file}`, because `audit-issues` still
walks story nodes with no issues file present. The findings reachable in that case are **1b**
(a `resolves:` key that names neither issue file) and **1h** (two live stories claiming one
key); both are read from story nodes alone. `1d` needs an open item and `1j` a resolved one,
so neither can fire without an issue file — do not expect them here. `triage` shares this
precondition (`steps/triage.md` Step T1) and will act on whatever this check reports.

```bash
uv run {pm_status} audit-issues --state-root {pm_state_root} --format json; echo "exit=$?"
uv run {skill-root}/scripts/audit-backlog.py --pm-status {pm_status} \
  --state-root {pm_state_root} --artifacts-root {implementation_artifacts} \
  --project-root {project-root} --format json
```
- `audit-issues` exit 4 with a non-empty `findings` list → flag `triage` · Priority: **High** ·
  note the finding ids
- `audit-issues` exit 4 with `findings: []` and an `error` → a malformed issue file or an
  unreadable story node (the node failed to parse, was not a mapping, or was not valid
  UTF-8); report the error as Check 13's result and never mark Check 13 ✓ — an empty
  `findings` list on exit 4 is not "clean" — then continue with the remaining checks
- any `fixed-candidate`, `obsolete-candidate`, or `duplicate-candidate` → flag `triage` ·
  Priority: **Medium** · note the count
- **count the `needs-review` verdicts whose `evidence` is `untraceable` and report them
  separately** — never fold them into a "0 candidates" line. Zero candidates over a backlog
  the auditor could not trace is blindness, not a clean bill, and the two read identically
  otherwise. Say:
  `{n} of {total} item(s) could not be traced to an artifact (evidence: untraceable) — the
  mechanical pass reached no verdict on them.` On a legacy backlog this is the normal result
  and not a defect in the backlog; it means the items predate the pointer fields the auditor
  reads
- no `{pm_state_root}` yet → ✓
- no findings, no candidates, **and nothing untraceable** → ✓

**Check 14 — Lock files tracked in git**
`pm-status.py`'s lock files — `epic-NNN.lock`, `issues.yaml.lock`, `pm-calibration.yaml.lock`
and `adr-register.yaml.lock` in `{pm_state_root}`, and a `.yaml.lock` sidecar beside some node
files below it — are empty flock targets and must never be committed. `pm-status.py` keeps
`*.lock` in `{pm_state_root}/.gitignore`, but a project that committed them before that rule
existed still tracks them. Run the check only if `{pm_state_root}` exists and `{project-root}`
is a git work tree — the first command below prints `true` (outside a repository it exits 128;
inside `.git/` it prints `false`):

```bash
git -C {project-root} rev-parse --is-inside-work-tree
git -C {project-root} ls-files -- '{pm_state_root}/*.lock'
```

The explicit `/` keeps the pattern inside the state root: `{pm_state_root}` is bound without a
trailing slash, and `state*.lock` would also match a sibling such as `state.lock`. A git
pathspec `*` also matches `/`, so the pattern reaches sidecars at any depth.
- Any path listed → flag `untrack-locks` · Priority: **Low** · note the count, and keep the
  list: Step HC3 prints it before HC5 asks
- `ls-files` exits 128 — `{pm_state_root}` lies outside the repository → report that as
  Check 14's result and skip the check: neither flag it nor mark it ✓
- None listed, no `{pm_state_root}` yet, or not a git work tree → ✓

**Check 15 — ADR home and register**
Run only if `{implementation_artifacts}` exists.

```bash
{spec_align} migrate-adrs --plan
```

- `actionable` non-empty → flag `migrate-adrs` · Priority: **Medium** · note the count, and
  how many are a `collision`
- `duplicates` non-empty → report only, and **do not** propose `migrate-adrs` for them:
  `{n} legacy ADR(s) are leftover duplicates of ADRs already in docs/adr/ (same number and
  slug). migrate-adrs will not move them. Review with diff and delete by hand.`
  Keying the recommendation on `moves` instead of `actionable` pointed already-migrated
  projects — the ones a renumbering run harms — straight at it.
- `register.lagging` is true → report
  `adr-register next {next} ≤ highest ADR on disk {highest_on_disk}`. This is report only:
  the next `adr-reserve` corrects it by itself
- otherwise → ✓

**Check 16 — Spec pointers**
Run only if `{implementation_artifacts}/spec/spec-index.md` exists, meaning the project has
run spec alignment.

```bash
{spec_align} check-pointers --all
```

- exit 1 → report every broken pointer it printed on stderr. This is report only: fix the
  story's `Spec:` line, or let story prep re-enrich it
- exit 0 → ✓, noting its pre-provenance count

**Check 17 — ADR links**
Run only if `{project-root}/docs/adr/` exists or any
`{implementation_artifacts}/epic-*/arch/adr-*.md` exists — the two homes `check-links` reads.

```bash
{spec_align} check-links
```

- exit 1 → report each ADR it names. This is report only: the next epic closure's spec sync
  links it
- exit 0 → ✓

**Check 18 — Unconfirmed spec changes that have been built upon**
Run only if `{project-root}` is a git work tree (`git -C {project-root} rev-parse --is-inside-work-tree`
prints `true`).

```bash
{spec_align} check-stale
```

- exit 1 → flag `triage` · Priority: **Medium**. Its spec pass confirms or rejects them;
  each later commit on the same file makes a clean revert less likely
- exit 0 → ✓

**Check 19 — Spec index freshness**
Run only if the index exists.

```bash
{spec_align} build --check
```

- exit 1 → report `spec index is stale`. This is report only: the next pm-execute run
  rebuilds it, or `{spec_align} build` rebuilds it now
- exit 0 → ✓

**Check 20 — BMad dependency resolution**
Every phase this package dispatches resolves against a real skill, or self-skips. A required
dependency that vanished under a project surfaces otherwise as a silently skipped gate
mid-epic — the failure `bmad-deps.py` exists to make visible, and nothing was calling it.

```bash
uv run {skill-root}/scripts/bmad-deps.py verify --project-root {project-root} --format json; echo "exit=$?"
```

- exit 3 → flag · Priority: **Critical** · name every unresolved **required** dependency. A
  required skill that does not resolve will not self-skip; the phase that dispatches it fails
  at the point of use, mid-run
- `baseline_drift` non-empty → report only · the declared inventory disagrees with
  `_bmad/_config/skill-manifest.csv` about what BMad ships. Informational: it means the
  inventory needs re-checking against this BMad version, not that the project is broken
- unresolved **optional** dependencies → report only · name them and the phases that will
  self-skip, so a missing phase later is expected rather than mysterious
- exit 0 and no drift → ✓

**Check 21 — State tree reachable and tracked**
Two states that look identical to a check that only looks at the configured path, and that
turn "no findings" into a wrong answer rather than a refusal.

```bash
uv run {skill-root}/scripts/detect-layout.py --artifacts {implementation_artifacts} \
  --project-root {project-root} --reachability --format json; echo "exit=$?"
```

- `orphaned` non-empty → flag · Priority: **Critical** · print each path. A state tree exists
  outside `{implementation_artifacts}`, which means `implementation_artifacts` was repointed
  and the history lives at the old path. **Report only — never move it**: which tree is
  current is a human decision, and the wrong choice loses the project's history
- `untracked` true → flag · Priority: **High** · `{implementation_artifacts}/state` is on disk
  but git ignores it. It is one `git clean` from gone and invisible to every other clone.
  Report only: the fix is a `.gitignore` edit, and which rule is catching it matters
- neither → ✓

> The probe is in `detect-layout.py`, not inline here, deliberately. Two step files already
> carried it as a shell pair with a comment asking the next person to keep them in sync; a
> third copy in the health check is what `CLAUDE.md` §4 is about. One tested implementation,
> and `scripts/tests/test-detect-layout.py` covers the orphan, the gitignore, the clean tree
> and the not-a-git-repo cases.

**Check 22 — Story document vs state node status**
A story's markdown frontmatter and its state node can disagree: `sync-story-doc` warns and
returns 0 when the document is missing or has no frontmatter, because the state transition it
follows is already durable. That is the right call at write time and leaves this drift behind.

For each story node in the state tree, compare `status` against the `status:` in
`{implementation_artifacts}/epic-XX/sprint-YY/stories/{story-key}.md`.

- Any disagreement → flag for report · Priority: **Medium** · list `{key}: state={a} doc={b}`.
  **Report only, never auto-correct.** Which side is right is a judgement: the doc may be a
  hand-edit that the state never saw, or the state may have moved on while the doc went stale.
  Same class as Check 11
- A story node whose document is absent → not a finding here; Check 11 owns that
- No disagreements → ✓

**Check 23 — Epic directory placement (sharded tree)**
The placement rule says an epic's directory lives in the folder named for its status. Check 8
enforces this only for the legacy split layout; the sharded tree had no equivalent, so an epic
whose folder and status disagree stayed wrong indefinitely — with both the detector and the
repair already built and simply never connected.

```bash
uv run {pm_status} report --state-root {pm_state_root} --format json
```

- Any epic whose containing folder does not match its `status` (`planned/`=`backlog`,
  `active/`=`in-progress`, `archived/`=`done`) → flag · Priority: **High** · name each, and
  propose the repair, which is a `git mv` of the whole directory:
  `uv run {pm_status} move-epic --state-root {pm_state_root} --epic {key} --to {status}`
- No mismatches → ✓

**Check 24 — Agent instruction block**
Bind `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py` and `{runtime}` by the
detection procedure in `l3io-execute/steps/shared/step-00-activate.md` §2, then run:

```bash
uv run {pm_status} sync-agent-instructions --runtime {runtime} \
  --project-root {project-root} --check
```

This is read-only and takes no lock. Act on the exit code, and keep 1 and 2 apart — they are
different findings with opposite remedies:

- Exit 1 (block absent for this harness) → flag · Priority: **Low** · name the file that
  would be written, and say that an agent without it does not know state is machine-written.
  The fix is the block procedure in `assets/module-setup.md` §6, which asks before touching a
  file that exists without markers — so it is **not** in Step HC6's sequence, and is run on
  request after the report
- Exit 2 (ambiguous markers, or the file is not valid UTF-8) → flag for **manual** repair ·
  Priority: **Medium** · print the script's message. **Never offered as a fix and never
  auto-run**: the file is the user's and its markers are already in a state the script refused
  to guess about
- Exit 0 → ✓
- Any other exit → not a finding; mention the exit code and continue

### Step HC3 — Report findings


Print the health check table. Use ✓ for passing checks, ⚠ for flagged items:

```
PROJECT HEALTH CHECK — {implementation_artifacts}
================================================================
Check                           Status                         Action
----------------------------------------------------------------
Status file naming              ⚠ sprint-status-active.yaml    rename-active
Status file layout              ✓ Split layout in use          —
State layout migration          ⚠ Both layouts present          migrate-state
Artifact-only stories           ⚠ 2 story artifact(s), no state bootstrap-state
Status file schema              ✓ All fields current           —
Status placement & backlog      ⚠ 1 misplaced epic, 3 nested  reconcile-status
Artifact layout                 ⚠ 3 flat file(s) detected     clean-layout
Status file ordering            ✓ All sorted                   —
Deferred code markers           ⚠ 2 new marker(s)             harvest-debt
AI instruction references       ✓ Current                      —
Migration backup files          ⚠ 1 .legacy file found         clean-legacy
Epic directory padding          ⚠ 1 legacy epic-{nn}/ dir       rename-epic-dirs
State/artifact drift            ⚠ 2 orphaned key(s)             — (report only)
Calibration provenance           ⚠ 4 poisoned sample(s)         redrive
Backlog integrity & audit       ⚠ 1 integrity, 4 candidate(s)  triage
Tracked lock files              ⚠ 3 *.lock tracked in git      untrack-locks
ADR home & register             ⚠ 2 ADR(s) in epic-*/arch/     migrate-adrs
Spec pointers                   ⚠ 1 broken pointer             — (report only)
BMad dependencies               ✓ all resolve                  —
State reachable & tracked       ✓ configured tree only         —
Story doc vs state              ⚠ 1 disagreement               — (report only)
Epic placement (sharded)        ⚠ 1 misplaced epic             move-epic
ADR links                       ⚠ 1 unlinked departure         — (report only)
Unconfirmed spec changes        ⚠ 1 built upon                 triage
Spec index freshness            ✓ Fresh                        —
Agent instruction block         ⚠ absent in CLAUDE.md          — (on request)
================================================================
```

If flagged items exist, append the recommended execution sequence (only flagged actions shown, in priority order):
```
Recommended actions (in order): rename-active → rename-epic-dirs → split-status → migrate-state → clean-layout → harvest-debt
```

If `untrack-locks` is flagged, print Check 14's `ls-files` list under the table — every path
the action would untrack. That is this action's dry run, shown before HC5 asks, as every other
action's dry-run output is.

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

1. `rename-active` (inline — see below)
2. `rename-epic-dirs` (inline — see below)
3. `migrate-schema`
4. `split-status`
5. `migrate-state`
6. `bootstrap-state`
7. `reconcile-status`
8. `clean-layout`
9. `sort-status`
10. `harvest-debt`
11. `migrate-adrs`
12. `triage`
13. `update-ai-rules`
14. `redrive`
15. `untrack-locks`
16. `clean-legacy`

`bootstrap-state` runs after `migrate-state` because migrate-state may have created the sharded
tree that bootstrap-state then augments with story nodes from the artifact tree. `redrive` must
run after `migrate-state` — it walks the sharded state tree, which does not
exist before that step — and after every other action that can add, move, or rewrite node
files (`reconcile-status`, `clean-layout`, `sort-status`), so it rebuilds calibration
samples from the most fully-corrected tree available. It runs before `clean-legacy` only
because that step is the fixed final tidy-up; nothing about `redrive` depends on backup files
still being present.

`migrate-adrs` runs before `triage` so that ADR paths a backlog item cites are already the new
ones when triage reads them. It keeps its own plan and confirmation (Step MA2), like `triage`
does, because it commits.

Before each action, print a separator header:
```
─── Running: {action-name} ──────────────────────────────────
```

Each action runs its full mode implementation from its own section. **Suppress the per-mode confirmation prompts** — the user already confirmed in HC5; proceed as if they answered yes at each mode's own confirm step. The per-mode dry-run output and verify steps still run and are shown.

**`triage` keeps its own confirmations here.** The rule above does not apply to it: every triage action resolves or rewrites backlog items, which the HC5 yes did not see item by item. It runs right after `harvest-debt`, so markers harvested in the same run are audited too.

**`migrate-adrs` keeps its own confirmation too** — it moves files and commits.

**`rename-active` (Check 1) has no mode file — run it here, inline.** It is one rename of a
legacy flat file. Re-check the precondition first rather than trusting Check 1's earlier
result, because an action run before this one may have changed the tree:

- If `{implementation_artifacts}/sprint-status-active.yaml` does not exist → nothing to
  rename; skip.
- If `{implementation_artifacts}/sprint-status.yaml` already exists → **conflict**. Do not
  rename and do not overwrite; print
  `Conflict: sprint-status.yaml already exists at {implementation_artifacts}. Cannot rename
  sprint-status-active.yaml — resolve manually (remove or merge the existing file first).`
  and treat this action as failed, per the stop-on-failure rule above.

Otherwise print the one-line dry run
(`Will rename: {implementation_artifacts}/sprint-status-active.yaml →
{implementation_artifacts}/sprint-status.yaml — content unchanged, filename only`), rename,
then re-parse `sprint-status.yaml` as YAML. If it does not parse, rename it back to
`sprint-status-active.yaml` and report
`FAILED — sprint-status.yaml is not valid YAML after rename. Restored. Parse error: {error}`.

**`rename-epic-dirs` (Check 10) has no mode file — run it here, inline.** It renames legacy
two-digit `epic-{nn}/` **artifact** directories to the three-digit `epic-{nnn}/` form, so each
matches its epic key `E{nnn}` and its `state/{status}/epic-{nnn}/` counterpart — the
identical-path-suffix property Check 11's drift diff depends on. Contents are never touched.

Re-scan the top level of `{implementation_artifacts}/` for `epic-[0-9][0-9]` directories. For
each, compute the three-digit destination by zero-padding the epic number; if that destination
already exists, record a **conflict** and skip it — never overwrite, never merge. Print the
rename map and the conflict count as this action's dry run, then rename each non-conflicting
directory and re-scan to confirm no two-digit directory remains except the recorded conflicts.

Report renamed and conflict counts. A remaining conflict needs manual resolution (merge or
remove one side) before Check 11's drift comparison can be trusted for that epic.

**`untrack-locks` (Check 14) has no mode file — run it here, inline.** First make sure
`{pm_state_root}/.gitignore` contains a `*.lock` line: create the file with that line if it is
absent, or append the line if it is missing, never rewriting or reordering the lines already
there. Then untrack the lock files Step HC3 listed, leaving them on disk:

```bash
git -C {project-root} rm -r --cached --quiet --ignore-unmatch -- '{pm_state_root}/*.lock'
```

This stages the removal for the user's next commit; it does not commit. It runs after every
action that invokes `pm-status.py` (and so may create lock files), and before `clean-legacy`,
the fixed final tidy-up.

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
