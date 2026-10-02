---
name: l3io-setup
description: Sets up the LiquidLogicLabs PM module in a project. Use when the user requests to 'install l3io-pm', 'configure l3io-pm', or 'setup l3io-pm'.
---

# l3io-setup — Module Setup

## Overview

Records the `l3io-pm` module's project-level settings in the BMad central config, and
registers its capabilities for the help system.

**This runs only when asked.** `l3io-pm` declares no required settings, so a correct install
has no `[modules.l3io-pm]` section at all and every PM skill works without one. An absent
section is **not** a first-run — see `references/config-resolution.md` §5. Nothing here is
triggered automatically.

## On Activation

1. Read `{skill-root}/assets/module.yaml` for module identity (`code`, `name`, `module_version`) and any
   declared `variables:`.
2. Resolve `{project-root}` to a real absolute path. The merge scripts reject an unresolved
   `{project-root}` token in a path argument, because writing to a literal `{project-root}/`
   directory under the skill folder is silent and hard to notice.
3. Follow `{skill-root}/assets/module-setup.md` — the canonical procedure, shared across every l3io
   module. It states what setup writes and, just as importantly, what it must not.

## What this writes

Only the two human-authored config layers, which the installer never regenerates:

- `{project-root}/_bmad/custom/config.toml` — team-scoped, committed
- `{project-root}/_bmad/custom/config.user.toml` — user-scoped, gitignored

```bash
uv run {skill-root}/scripts/merge-config.py \
  --project-root "{resolved-project-root}" \
  --module-yaml  "{skill-root}/assets/module.yaml" \
  --answers      "{answers-json-path}"
```

## What this does not write

`_bmad/_config/bmad-help.csv` — **the installer assembles it** from each module's own
`assets/module-help.csv` at install time. `{skill-root}/scripts/merge-help-csv.py` exists for the module
contract and for manual re-registration after an interrupted install; this skill does not call
it, because two writers on one file is how that file drifts.

## Completion

Report which layers were written and which keys landed in each, then print the module greeting
from `assets/module.yaml`.

## `scripts/pm-status.py` — carried, never invoked here

This skill also ships `scripts/pm-status.py` (~327 KB). Nothing in this file or in
`assets/module-setup.md` calls it — that is deliberate, not dead payload left behind by a
refactor. `l3io-setup` is `pm-status.py`'s one payload copy for the whole `l3io-pm` module
(Task 11A): `l3io-execute`, `l3io-plan`, and `l3io-sync` each self-install it from
here, reading `{skill-root}/../l3io-setup/scripts/pm-status.py` at their own activation
(`l3io-execute/steps/shared/step-00-activate.md` §2, and each of the three carries its own
copy), because `.claude-plugin/marketplace.json` declares
all five `l3io-pm` skills as one unit — provided the installer accepts each skill's SKILL.md
frontmatter (see `step-00-activate.md` §2's own note on this; a rejected sibling is not this
skill's failure to guard against, that guard already lives there). Before removing this file
as apparent dead weight, check those three skills' step-00-activate.md first — this is the one
file across the whole package they depend on being here.
