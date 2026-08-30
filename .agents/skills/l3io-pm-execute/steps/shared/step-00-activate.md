# Step 00: Activate l3io-pm Module

Communicate all responses in `{communication_language}`.

This step runs first in every l3io-pm skill. Complete all actions in order before loading
any subsequent step file.

---

## 1. Load module configuration

Resolve config through BMad core's resolver — the full contract, including every
binding and its default, is `{skill-root}/references/config-resolution.md`:

```bash
uv run --python 3.11 {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}
```

If the resolver is missing or the command fails, BMad core is not installed in this
project: **BLOCKED** — tell the user to run the BMad installer. Do not write config
yourself and do not continue.

`modules.l3io-pm` being absent is **not** a first-run and **not** an error — it means the
module has no project-level overrides, which is the normal state. Bind the defaults below
and continue. Load `{skill-root}/assets/module-setup.md` only when the user explicitly
passes `setup`, `configure`, or `install`.

Extract and bind from the resolved JSON:
- `{communication_language}` — `core.communication_language` (default `English`)
- `{output_folder}` — `core.output_folder` (default `{project-root}/_bmad-output`)
- `{implementation_artifacts}` — `modules.l3io-pm.implementation_artifacts`
  (default `{output_folder}/implementation-artifacts`)
- `{planning_artifacts}` — `modules.l3io-pm.planning_artifacts`
  (default `{output_folder}/planning-artifacts`)
- `{model}` — `modules.l3io-pm.default_model` (default `claude-opus-5`). The model id every
  `cost` in this project is priced against. Pass it as `--model {model}` on `estimate-story`,
  `estimate-rollup`, and every `set-actual` that carries token counts. **Not optional** —
  leaving it unbound prices every estimate at `claude-opus-5` regardless of what the project
  actually runs on, and the same token volume prices ~2× apart between a $3/M and a $10/M
  input tier. An unknown id is a hard error, exit 2, never a silent fallback.
- `{token_rates_json}` — `modules.l3io-pm.token_rates`, serialized to compact JSON; empty
  when the key is absent, which is the normal case (the shipped rate table applies). When it
  is **non-empty**, add `--token-rates '{token_rates_json}'` to `estimate-story`,
  `estimate-rollup`, `set-actual`, **and `verify`**; when it is empty, omit the flag
  entirely. Passing it to the writers but not to `verify` makes `verify` recompute `cost`
  against the shipped rates and fail every node the override priced. See
  `references/config-resolution.md` §3.
- Set `{pm_state_root}` = `{implementation_artifacts}/state`
- Set `{pm_issues_file}` = `{pm_state_root}/issues.yaml`
- Set `{pm_calibration_file}` = `{pm_state_root}/pm-calibration.yaml`

## 2. Install pm-status.py

Self-install compares the installed copy's **bytes** against this one and reinstalls on any
difference, so a project pinned to a stale copy heals itself on the next run. It skips only a
byte-identical copy, and refuses to overwrite a strictly newer one. Pass `--force` to
reinstall regardless.

Self-install runs here — **before** layout detection — deliberately. Self-install is
layout-independent (it copies a file and needs no state), so nothing in detection depends on
it, and running it first guarantees a current script whichever branch detection takes below.
This also keeps an upgrading user from getting stuck on a stale installed copy: a legacy
layout blocks in section 3 and sends the user to `/l3io-util-doctor migrate-state`, and that
command needs a current `{pm_status}` to succeed — which this section guarantees regardless of
which layout branch section 3 takes.

```bash
uv run {skill-root}/scripts/pm-status.py self-install \
  --dest {project-root}/_bmad/scripts/pm-status.py
```

If `uv` is unavailable, use `python3` instead. A "skipped — already up to date"
message is normal. Failure here is BLOCKED.

Bind `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py` for use in all
subsequent steps.

Bind `{runtime}` — passed as `--runtime` to every `set-actual` and `verify` call
(`references/metrics-contract.md` §3). The value must be **exactly** `claude` or
`other` — `pm-status.py` declares `--runtime` with `choices=["claude", "other"]` and
rejects anything else with exit 2, so never widen this to a runtime name or version
string. The criterion is a capability, not a brand check: bind `claude` only when this
execution can read its own session transcript's `usage` fields to capture exact
`tokens_k`/`cost` for the session (Claude Code, or any Claude-based agent with that
transcript access); bind `other` otherwise. **Default to `other` when uncertain** — it
is the permissive value, allowing `N/A` for `tokens_k`/`cost`, while `claude` forbids
`N/A` there; guessing `claude` without the ability to produce exact figures would either
block every write or invite a fabricated number, and both are worse than an honest
`N/A`. Do not treat this default as a bug to "fix" later — it is the deliberate
fail-safe direction.

## 3. Detect state layout

Count how many of these three layouts are present — do **not** stop at the first match:

```bash
SHARDED=$([ -d "{implementation_artifacts}/state" ] && echo 1 || echo 0)
LEGACY_EPIC=$([ -d "{project-root}/_bmad/state" ] && echo 1 || echo 0)
LEGACY_FLAT=$([ -f "{implementation_artifacts}/sprint-status.yaml" ] && echo 1 || echo 0)
echo "sharded=$SHARDED legacy-per-epic=$LEGACY_EPIC legacy-flat=$LEGACY_FLAT"
```

**If more than one is 1** → halt immediately. An interrupted migration left state in two
places, and guessing which is authoritative would fork the project's state:
```
BLOCKED: multiple state layouts detected (sharded=$SHARDED legacy-per-epic=$LEGACY_EPIC legacy-flat=$LEGACY_FLAT). An earlier migration
did not finish. Do not run any l3io-pm skill until this is resolved — inspect both
locations and remove the stale one, then re-run /l3io-util-doctor migrate-state.
```

**If only sharded** → current layout. Continue to section 4.

**If only the legacy per-epic layout or only the legacy flat layout** → halt:
```
⚠️  Legacy state layout detected (legacy per-epic layout = _bmad/state/, legacy flat layout = flat sprint-status.yaml).
Run /l3io-util-doctor migrate-state to upgrade before continuing.
```
BLOCKED: legacy state layout — migrate required. (`{pm_status}` was just self-installed in
section 2, so `migrate-state` runs against a current copy.)

**If all three are 0** → possible first run. Before creating anything, rule out an orphan
caused by `implementation_artifacts` having been repointed:

```bash
git -C {project-root} ls-files -- '*/state/active/epic-*/epic.yaml' 'state/active/epic-*/epic.yaml' 2>/dev/null | head -5
find {project-root} -maxdepth 5 -type d -name active -path '*/state/*' 2>/dev/null | head -5
```

The second pathspec (`state/active/epic-*/epic.yaml`, no leading `*/`) catches the case where
`implementation_artifacts` equals `project-root`: git's fnmatch-pathname semantics require at
least one literal path segment before `state/`, so the first pathspec alone would miss a
root-level match.

If either prints a path that is not under `{implementation_artifacts}/state`, halt:
```
BLOCKED: state found at <printed-path> but implementation_artifacts resolves to
{implementation_artifacts}. Did implementation_artifacts change? Refusing to start a
blank project over existing state.
```

If both print nothing → genuine first run. Continue to section 4.

## 4. Create state directories

```bash
mkdir -p {pm_state_root}/active {pm_state_root}/planned {pm_state_root}/archived
mkdir -p {planning_artifacts}
```

Verify the state root is not gitignored — this is what keeps state in version control:

```bash
git -C {project-root} check-ignore -q {pm_state_root} && echo IGNORED || echo TRACKED
```

If `IGNORED`, halt:
```
BLOCKED: {pm_state_root} is gitignored. Project state must be committed. Add to .gitignore:
  !{pm_state_root}/
  !{pm_state_root}/**
```

## 5. List active epics

```bash
ls -d {pm_state_root}/active/epic-*/ 2>/dev/null || echo "(none)"
```

Bind `{active_epic_keys}` = the `E{nnn}` key for each directory found (`epic-001` → `E001`).
An empty list is valid on first run.

## 6. Verify schema of files this skill will touch (if any active epics exist)

If `{active_epic_keys}` is non-empty AND this skill is `l3io-pm-execute` or `l3io-pm-plan`,
run for each epic key in scope:

```bash
python3 {pm_status} verify --state-root {pm_state_root} --epic {epic_key} --scope epic
```

A FAIL result means the epic's files are corrupted. Halt with:
```
BLOCKED: schema verify failed for {epic_key} — investigate before continuing.
```

A PASS or "epic absent" result is fine.

## 7. Bind session ID

Generate and bind `{session_id}` — a stable unique identifier for this execution session
(e.g., `l3io-pm-{iso_timestamp}-{random_suffix}`). This value must remain constant for the
lifetime of this skill invocation and is used by set-lock / check-lock to identify the
owning session. Generate it once here; never regenerate it in later steps.

**Only an orchestrator generates one.** If your context block supplies `session_id`, that
value is the run's — bind it and do not mint another. Two ids for one run cannot be
reconciled afterwards: `events.jsonl` is append-only and the stamp is all there is.

## 8. Load the state and metrics digest

```
{skill-root}/steps/shared/step-00-digest.md
```

Load it now and keep it in context for the rest of this invocation. It carries the keys,
subcommand signatures, exit codes, the estimates-and-actuals HARD RULE, the `{agent_contract}`
binding, and a routing table to the reference section a given question needs.

It is a separate file so that a dispatched subagent — which inherits everything sections 1–7
established and must not redo it — can load the digest alone.

## 9. Output status line

```
Step 00 complete — state: {pm_state_root}, active epics: {count_of_active_epic_keys}, pm-status: installed, runtime: {runtime}
```
