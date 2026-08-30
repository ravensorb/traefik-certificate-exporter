---
name: l3io-pm-sync
description: Bidirectional sync between l3io-pm state and GitHub Issues. Modes: setup, push, pull, sync, status (default).
---

# l3io-pm-sync

Communicate all responses in `{communication_language}`.

## Conventions

- `{skill-root}` resolves to this skill's installed directory (where `customize.toml` lives).
- `{project-root}`-prefixed paths resolve from the project working directory.

## On Activation

Run: `python3 {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --key workflow`

If the script fails, read `{skill-root}/customize.toml` directly.

Load `{skill-root}/assets/module-setup.md` first **only** when the user passes `configure` or
`install`. Note that `setup` is *not* a module-setup trigger in this skill — it selects the
`setup` mode below, which configures GitHub sync. Config is resolved in step-00-activate per
`{skill-root}/references/config-resolution.md`; an absent `modules.l3io-pm` section means the
module has no overrides, not that it needs setup.

## Execution

Parse the invocation argument to determine mode:

| Argument | Mode | Description |
|---|---|---|
| (none) or `status` | `status` | Show sync state and drift report |
| `setup` | `setup` | Detect platform (GitHub), verify auth, verify/create `_bmad/sync-state.yaml` |
| `push` | `push` | Create/update GitHub Issues for unmapped/changed local entities, record mappings |
| `pull` | `pull` | Read mapped issue state, mark closed-issue stories `done` |
| `sync` | `sync` | Bidirectional sync (push then pull) |

Bind `{sync_mode}` = parsed mode.

Load and execute in order:

```
{skill-root}/steps/shared/step-00-activate.md
{skill-root}/steps/sync/step-02-detect-platform.md
{skill-root}/steps/sync/step-03-operations.md
{skill-root}/steps/sync/step-04-resolve.md
```
