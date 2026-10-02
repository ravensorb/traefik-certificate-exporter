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
and continue. This skill never loads module setup, regardless of argument —
`/l3io-setup` is the module's setup entry point.

Bind `{l3io_pm_section_absent}` = `true` when `modules.l3io-pm` is absent from the resolved
JSON, else `false`. This reuses the same resolved JSON already read above — it is not a second
resolve. It exists solely for the once-per-project setup-pointer check in `l3io-execute` and
`l3io-plan` (`config-resolution.md` §5) — not once per session: there is no cross-invocation
session identifier available, so a session-keyed check would fire on every invocation instead.
The pointer's only useful message is "you have not configured this," so it must say nothing
once a section exists. This flag is never a trigger for setup itself — no argument to this
skill triggers module setup; `/l3io-setup` is the module's setup entry point.

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
- `{model_story_simple}` — `modules.l3io-pm.model_story_simple` (default `{model}`). Model
  used when dispatching a story dev agent for a `classification: simple` story. Used as the
  `model:` binding in the dispatch context block and as `--model` on that story's `set-actual`.
- `{model_story_standard}` — `modules.l3io-pm.model_story_standard` (default `{model}`). Same
  for `classification: standard` stories.
- `{model_story_complex}` — `modules.l3io-pm.model_story_complex` (default `{model}`). Same
  for `classification: complex` stories.
- `{model_review}` — `modules.l3io-pm.model_review` (default `{model}`). Model used when
  dispatching `bmad-code-review` from the dev loop. Passed through dispatch context so the dev
  loop agent can use it when spawning the reviewer.
- `{model_prep}` — `modules.l3io-pm.model_prep` (default `{model}`). Model for sprint prep
  agents.
- `{model_closure}` — `modules.l3io-pm.model_closure` (default `{model}`). Model for sprint
  and epic closure agents.
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

`pm-status.py` ships once per module, not once per skill. For `l3io-pm` it lives at
`l3io-setup/scripts/pm-status.py` — the module's home — not here in this skill's own
`scripts/`. That is a module-home read, not the cross-skill path read `l3io-help/SKILL.md`
says it avoids for its own, unrelated staleness question: `.claude-plugin/marketplace.json`
declares the whole `l3io-pm` plugin — all five of its skills, including `l3io-setup` — as
one unit, and BMad's installer resolves and copies that unit as siblings under
`.claude/skills/`. `/l3io-setup` itself stays **optional**: nothing here requires the setup
skill to ever have been *run*, only installed beside this one.

**That co-installation is conditional, not absolute — say so plainly.** BMad's installer only
carries a skill into `.claude/skills/` and `_bmad/_config/skill-manifest.csv` when its
`SKILL.md` frontmatter strict-YAML-parses and its `name:` equals its directory name; a skill
that fails either test is silently dropped from the plugin, with no install-time warning. This
happened for real: `l3io-sync/SKILL.md`'s unquoted `Modes: …` line broke the parse and a
real install shipped only four of `l3io-pm`'s five skills until it was quoted (Task 11A fix
round 1; `check:docs`'s `skill-frontmatter` check now guards this mechanically going forward,
but a project on an older, unpatched copy of this package could still hit it).

First confirm the sibling payload is actually on disk — the manifest states the intent, but
only this on-disk check states the fact, whether the cause is the installer dropping the
skill or someone hand-copying a single skill directory out of the plugin (or shipping a
partial checkout). Either way the failure must name the missing piece rather than fail
silently or opaquely inside `uv run`:

```bash
test -f {skill-root}/../l3io-setup/scripts/pm-status.py
```

If absent, halt:
```
BLOCKED: l3io-setup/scripts/pm-status.py is missing beside this skill.
Check {project-root}/_bmad/_config/skill-manifest.csv for an l3io-setup row: if it is
missing, the installer rejected that skill (a SKILL.md frontmatter or naming defect) and
reinstalling the l3io-pm plugin will reproduce the same result until that is fixed upstream.
If the row IS present, a skill directory was likely hand-copied or the checkout is partial —
reinstalling the l3io-pm plugin resolves that case.
```

Self-install compares the installed copy's **bytes** against this one and reinstalls on any
difference, so a project pinned to a stale copy heals itself on the next run. It skips only a
byte-identical copy, and refuses to overwrite a strictly newer one. Pass `--force` to
reinstall regardless.

Self-install runs here — **before** layout detection — deliberately. Self-install is
layout-independent (it copies a file and needs no state), so nothing in detection depends on
it, and running it first guarantees a current script whichever branch detection takes below.
This also keeps an upgrading user from getting stuck on a stale installed copy: a legacy
layout blocks in section 3 and sends the user to `/l3io-doctor migrate-state`, and that
command needs a current `{pm_status}` to succeed — which this section guarantees regardless of
which layout branch section 3 takes.

```bash
uv run {skill-root}/../l3io-setup/scripts/pm-status.py self-install \
  --dest {project-root}/_bmad/scripts/pm-status.py
```

If `uv` is unavailable, use `python3` instead. A "skipped — already up to date"
message is normal. Failure here is BLOCKED.

Bind `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py` for use in all
subsequent steps.

Bind `{runtime}` — passed as `--runtime` to every `set-actual` and `verify` call
(`references/metrics-contract.md` §3). The value must be **exactly** one of `claude`,
`codex`, `copilot`, or `other` — `pm-status.py` rejects anything else with exit 2.
The criterion is a **capability**, not a brand check: choose the value whose token capture
procedure you can actually execute.

**Detection procedure:**

1. **`claude`** — bind when `$CLAUDE_CODE_SESSION_ID` is set in the environment. This is the
   Claude Code session identifier; its presence means the `pm-status.py usage` subcommand can
   read the session transcript to extract exact per-class token counts.

2. **`codex`** — bind when running inside Codex CLI and session JSONL files are available at
   `~/.codex/sessions/`. Confirmation: `ls ~/.codex/sessions/ 2>/dev/null | head -1` returns a
   session directory. Token capture reads `token_count` events from `rollout-*.jsonl`; sum
   `input_tokens`, `output_tokens` + `reasoning_output_tokens` (folded into output),
   and `cached_input_tokens` (→ `cache_read`); `cache_write` is `0` (Codex CLI drops this
   field — see metrics-contract.md §3).

3. **`copilot`** — bind when running inside a GitHub Copilot agent session (VS Code Copilot
   extension or Copilot Cloud Agent) where `$CLAUDE_CODE_SESSION_ID` is absent and Codex CLI
   session files are not present. Token capture sums `usage.prompt_tokens` (→ input) and
   `usage.completion_tokens` (→ output) across every API response in the node's dispatch
   window. No cache split is accessible; cost is recorded as N/A.

4. **`other`** — bind in all other cases, including when token data is genuinely not observable.
   Tokens and cost are recorded as N/A; `man_hours`, `hitl_hours`, and `elapsed_hours` are
   still required as real numbers.

**Default to `other` when uncertain** — it is the permissive value, allowing N/A for
tokens/cost. Guessing `claude` without transcript access, or `codex` without readable session
files, would either block every write (exit 2 on `--tokens-na`) or invite a fabricated number,
and both are worse than an honest N/A.

## 2.5. Verify the l3io-doctor sibling module is installed

`l3io-doctor` is a required intra-package module (CLAUDE.md "Dependencies") — the PM
skills forward migrations, health checks, and the plan-aware progress dashboard to it, and
`l3io-help` invokes `check-pm-status` on every activation. A standard install carries the
whole marketplace bundle so this is only false when someone has manually stripped the module.

The check probes both the 6.12 and pre-6.12 skill layouts, project-root first then user home,
matching `bmad-deps.py`'s resolve() (which cannot help here because it *is* the doctor):

```bash
if   [ -f "{project-root}/.claude/skills/l3io-doctor/SKILL.md" ] \
  || [ -f "{project-root}/.claude/commands/l3io-doctor.md" ] \
  || [ -f "$HOME/.claude/skills/l3io-doctor/SKILL.md" ] \
  || [ -f "$HOME/.claude/commands/l3io-doctor.md" ]; then
  doctor=present
else
  doctor=absent
fi
```

**Warn but do not block.** This skill can complete without the doctor for its own core path;
the failure is deferred to whichever specific step tries to forward to it (`migrate-state`,
`bootstrap-state`, `check-pm-status`). Surfacing the warning up front turns "skill not found"
into a diagnosable install anomaly instead of a downstream mystery.

When `doctor=absent`, print exactly once at activation (do not repeat later):

```
⚠️  l3io-doctor is not installed — this is a required module of the LiquidLogicLabs
    extension. The marketplace bundle in .claude-plugin/marketplace.json ships it alongside
    l3io-pm, so this state is an install anomaly. Some steps below (state-layout migrations,
    the progress dashboard, and `check-pm-status`) will fail if reached. Reinstall
    the extension with `--modules ...,l3io-util,...` or reinstall the plugin bundle whole to
    restore it.
```

Continue to section 3 either way.

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
locations and remove the stale one, then re-run /l3io-doctor migrate-state.
```

**If only sharded** → current layout. Continue to section 4.

**If only the legacy per-epic layout or only the legacy flat layout** → halt:
```
⚠️  Legacy state layout detected (legacy per-epic layout = _bmad/state/, legacy flat layout = flat sprint-status.yaml).
Run /l3io-doctor migrate-state to upgrade before continuing.
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

If `{active_epic_keys}` is non-empty AND this skill is `l3io-execute` or `l3io-plan`,
run for each epic key in scope:

```bash
uv run {pm_status} verify --state-root {pm_state_root} --epic {epic_key} --scope epic
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
