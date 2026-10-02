# overlay — generate, diff and verify BMad customization overlays

> **This is a specification, not a live mode.** There is no `overlay` keyword on
> `/l3io-doctor`, and this file is not under `steps/` — nothing loads it at runtime. It
> describes the mode Phase 3 will restore, once this directory holds overlay content. Until
> then all three actions below would report "nothing ships yet" by construction: `assets/overlays/`
> contains this file and `README.md` and no TOML, so `diff` and `verify` have nothing to read
> and `list` only re-prints what `bmad-customize` already reports about the install. Restoring
> it means moving this file back under the skill's `steps/` directory and adding its routing
> row in `SKILL.md` — a mode is a file plus a table row.

Specified as `overlay [list|diff|verify]`. Default action (no sub-argument, or an unrecognized
one) is `list`. Owner of the BMad customization layer: what an overlay is, where it is staged,
and how to check it landed. Phase 3 (`docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md`)
fills `assets/overlays/` with actual TOML; this document is the contract those files land in.

## What this mode may not do

**It never writes `{project-root}/_bmad/custom/`.** BMad Builder is explicit: *"There is no
supported pattern for modules to write into `_bmad/custom/`"* — that space belongs to the end
user. This mode stages a file and hands the user one command to place it themselves. If that
constraint is ever lifted upstream, change it here and record it in an ADR; do not quietly
start writing there because it would save the user a step.

## Actions

| Action | Effect |
|---|---|
| `list` (default) | What is customizable in this install, and which overlays l3io ships |
| `diff` | Staged overlay vs. the currently resolved merge, per skill |
| `verify` | Assert a placed overlay actually merged |

**Step OV1 — Load config**

Config is already resolved and `{implementation_artifacts}` bound per the *On Activation*
section above. No additional binding is needed before any of the three actions below.

## `list`

**Step OV2 — Enumerate what BMad exposes**

```bash
uv run {project-root}/.claude/skills/bmad-customize/scripts/list_customizable_skills.py \
  --project-root {project-root}
```

This is a BMad core script installed by `bmad-customize` at a fixed path in the target
project — never bundled with this skill (same rule as `resolve_config.py` and
`resolve_customization.py`; see root `CLAUDE.md`). If it is missing, `bmad-customize` is not
installed here: report `BLOCKED: bmad-customize is not installed — install it to enumerate
customizable skills.` and stop.

**Step OV3 — Report**

For each skill the script lists, report its name, the root key it takes (`agent` or
`workflow`), and whether `assets/overlays/` in this skill ships an overlay for it (by
filename match, `<skill>.toml`). A skill whose `customize.toml` does not expose a field an
overlay would need is reported as such — never invent a field that is not actually there.

Today `assets/overlays/` is empty (see its own `README.md`) — Phase 3 populates it — so every
row reports "no l3io overlay ships for this skill yet." That is expected, not a defect.

## `diff`

**Step OV4 — Render each staged overlay**

For each `<skill>.toml` under `{skill-root}/assets/overlays/`, copy it to
`{implementation_artifacts}/l3io/overlays/<skill>.toml` (create the directory if absent). This
is the staging path — it is never `_bmad/custom/`.

**Step OV5 — Diff against the resolved merge**

```bash
uv run {project-root}/_bmad/scripts/resolve_customization.py \
  --skill {project-root}/.claude/skills/<skill> --project-root {project-root} --key <root-key>
```

`<root-key>` is `agent` or `workflow` per the Skill Authoring Conventions table for that
skill (root `CLAUDE.md`) — using the wrong one means the diff is comparing against a merge
BMad would ignore. Show the staged TOML next to the resolved output so the user can see what
placing it would change.

**Step OV6 — Print exactly one placement command per staged file**

**Print this command for the user to run; never run it yourself.** Placing the file is the act
this mode exists not to perform — `_bmad/custom/` is the user's space, and writing there is this
mode's defining prohibition.

```
cp {implementation_artifacts}/l3io/overlays/<skill>.toml {project-root}/_bmad/custom/<skill>.toml
```

State plainly that the team layer (`_bmad/custom/<skill>.toml`) is committed and the
`.user.toml` layer (`_bmad/custom/<skill>.user.toml`) is gitignored, so the user is choosing
scope by choosing the filename — this mode never decides that for them.

If `assets/overlays/` has no files, report `No l3io overlays ship yet — nothing to diff.
assets/overlays/README.md explains why.` and stop.

## `verify`

**Step OV7 — Resolve what actually merged**

For each overlay this mode ships (today: none — see `list`), run:

```bash
uv run {project-root}/_bmad/scripts/resolve_customization.py \
  --skill {project-root}/.claude/skills/<skill> --project-root {project-root} --key <root-key>
```

**Step OV8 — Compare and report per overlay**

Compare the resolved output against what the staged overlay intended:

- **placed and merged** — the resolved output reflects the overlay's fields.
- **placed but not merged** — a file exists at `_bmad/custom/<skill>.toml` (or
  `.user.toml`) but the resolved output does not reflect it. This is the interesting case: it
  usually means the root key is wrong (`[agent]` where `[workflow]` was needed), which BMad
  ignores **silently** rather than erroring.
- **not placed** — no file exists at either `_bmad/custom/` path for that skill.

Report each overlay's status in a table; do not stop at the first mismatch.

## Phase 3

This mode ships with no overlay content — `assets/overlays/` is created empty, with a
`README.md` stating why. The overlays themselves — the `l3io-spec-alignment` review layer,
the lens exports, `implementation_handoff`, `persistent_facts`, `on_complete` — are Phase 3 of
`docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md`. Running `list`,
`diff`, or `verify` today is expected to report "nothing ships yet" rather than fail.

---

Report:
- `list` → `DONE — <n> customizable skill(s) found; <m> l3io overlay(s) available (0 until
  Phase 3).`
- `diff` → `DONE — <n> overlay(s) staged to {implementation_artifacts}/l3io/overlays/.` or
  `DONE — no l3io overlays ship yet.`
- `verify` → `DONE — <n> placed-and-merged, <p> placed-but-not-merged, <u> not-placed.`
- `bmad-customize` or the core resolver absent → `BLOCKED: <which script> is not installed —
  <what to install>.`
- Any other failure → `FAILED: <reason>`
