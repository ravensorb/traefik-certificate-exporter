# Overlays — empty by design (Phase 3)

This directory is where `l3io-doctor`'s `overlay` mode will look for customization TOML
this package ships for BMad core skills — `bmad-build`, `bmad-review`, and the story skills. It
holds no TOML on purpose: Phase 1/2 ("scaffold the overlay owner") wrote the mode's contract,
and the overlay **content** is Phase 3.

**The mode itself is not installed.** Its contract lives beside this file as
`overlay-mode.md`, not under `steps/`, and `/l3io-doctor` has no `overlay` keyword — all
three of its actions would report "nothing ships yet" while this directory has no TOML in it.
Phase 3 restores the keyword by moving that contract back under the skill's `steps/`
directory and adding its routing row in `SKILL.md`.

## What lands here, once Phase 3 ships it

Per `docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md` §5 (Phase 3):

- `review_layers` append, `id = "l3io-spec-alignment"` — runs `spec-align.py check-pointers`
  against the diff.
- `[[workflow.lenses]]` entries exposing `l3io-sec-redteam`'s threat lenses and
  `l3io-arch-review`'s standards.
- `persistent_facts` with `file:` globs — story technical ACs and `spec-index.md` as run facts.
- `implementation_handoff` override dispatching the l3io dev agent with `Files in scope` and
  read-scope discipline.
- `on_complete` writing back through `pm-status.py set-status`, replacing the flat-file write.

Each overlay is named `<skill>.toml` (e.g. `bmad-build.toml`), using the root key
(`[agent]` or `[workflow]`) that skill's own `customize.toml` requires — see root `CLAUDE.md`'s
Skill Authoring Conventions table.

## The one rule that does not change in Phase 3

**Nothing in this directory is ever written to `{project-root}/_bmad/custom/` by this
package.** BMad Builder is explicit: *"There is no supported pattern for modules to write into
`_bmad/custom/`"* — that space belongs to the end user. `overlay diff` will render a file from here
to a staging path and hand the user one `cp` command; `overlay verify` will check whether they
ran it. If Phase 3 ever needs to change that, it is a decision recorded in an ADR, not a quiet
addition to a script.
