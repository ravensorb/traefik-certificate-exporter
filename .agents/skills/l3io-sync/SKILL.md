---
name: l3io-sync
description: "Bidirectional sync between l3io-pm state and GitHub Issues. Use when the user wants to push epics, sprints and stories to GitHub Issues, pull status back, or check what has drifted between the two. Modes: setup, push, pull, sync, status (default)."
---

# l3io-sync

Communicate all responses in `{communication_language}`.

## Conventions

- `{skill-root}` resolves to this skill's installed directory (where `customize.toml` lives).
- `{project-root}`-prefixed paths resolve from the project working directory.

## On Activation

Run: `uv run {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --key workflow`

If the script fails, read `{skill-root}/customize.toml` directly.

`configure` and `install` are not recognized arguments here — `/l3io-setup` is the
module's setup entry point. `setup` is not a module-setup trigger in this skill either — it
selects the `setup` mode below, which configures GitHub sync, a different thing. Config is
resolved in step-00-activate per `{skill-root}/references/config-resolution.md`; an absent
`modules.l3io-pm` section means the module has no overrides, not that it needs setup.

## Execution

Parse the invocation argument to determine mode:

| Argument | Mode | Description |
|---|---|---|
| (none) or `status` | `status` | Show sync state and drift report |
| `setup` | `setup` | Detect platform (GitHub), verify auth, verify/create `_bmad/sync-state.yaml` |
| `push` | `push` | Create/update GitHub Issues for unmapped/changed local entities, record mappings |
| `pull` | `pull` | Read mapped issue state, mark stories `done` whose issue closed as completed |
| `sync` | `sync` | Bidirectional sync (push then pull) |

Bind `{sync_mode}` = parsed mode.

Do not add the once-per-project `/l3io-setup` pointer (`config-resolution.md` §5) here:
`notice` is keyed on the notice key alone, not on a session, so nothing here technically
prevents wiring it in — this is a placement choice, not a guard this skill fails. The pointer
belongs where a user is about to run PM work and could act on it; this skill only syncs to
GitHub. It is wired into `l3io-execute`/`l3io-plan` only.

Load and execute in order:

```
{skill-root}/steps/shared/step-00-activate.md
{skill-root}/steps/sync/step-02-detect-platform.md
{skill-root}/steps/sync/step-03-operations.md
{skill-root}/steps/sync/step-04-resolve.md
```
