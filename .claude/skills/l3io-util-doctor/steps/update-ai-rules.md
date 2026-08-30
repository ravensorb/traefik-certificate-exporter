## Update AI Rules Mode

Invoked with `update-ai-rules` argument, or automatically from `steps/split-status.md` (Split Status Mode) Step S9. Scans for AI system instruction files in the project and updates any references to a **legacy** state layout — the flat `sprint-status*.yaml` files or the legacy per-epic `_bmad/state/` tree — so they describe the **current sharded state tree** under `{pm_state_root}`. For instruction files that already exist: updates existing references. For the currently running AI system's file that does not yet exist: creates it with a state layout section. Never creates instruction files for other AI systems. Safe to run repeatedly — already-updated files are skipped.

**This mode writes into the consuming repo's own instruction files, and those files then
steer every future agent in that repo.** It must therefore only ever emit the current
layout. Emitting the decommissioned three-file layout here would teach every agent in the
consuming repo to look for files the PM skills hard-block on.

### Supported AI instruction file locations

| AI System | Instruction file |
|---|---|
| Claude Code | `{project-root}/CLAUDE.md` |
| GitHub Copilot | `{project-root}/.github/copilot-instructions.md` |
| Google Gemini | `{project-root}/GEMINI.md` |
| Generic agents | `{project-root}/AGENTS.md` |
| Cursor | `{project-root}/.cursorrules` or `{project-root}/cursor.md` |
| Cline | `{project-root}/.clinerules` or `{project-root}/CLINE.md` |

### Detection rule

A reference is flagged for update if it names any legacy state location — `sprint-status.yaml`, `sprint-status-backlog.yaml`, `sprint-status-archived.yaml`, `sprint-status-planned.yaml`, `sprint-status-issues.yaml`, `E{nnn}-status.yaml`, or `_bmad/state/` — and is NOT immediately followed by `.legacy`. A reference is already current, and skipped, when its paragraph or section describes the sharded tree (mentions `state/active/`, `state/planned/`, `state/archived/`, or `{pm_state_root}`).

Note the direction of travel: the three-file split (`sprint-status-backlog.yaml` / `sprint-status-archived.yaml`) is itself a **legacy** layout now and is flagged for update, not treated as the target.

### Steps

**Step AR1 — Scan**

Check each well-known instruction file location. For each file that exists, grep for `sprint-status[-a-z]*\.yaml`, `E[0-9]*-status\.yaml`, and `_bmad/state` (case-sensitive) and collect all matches with surrounding context (2 lines before/after). Apply the detection rule. Build a findings list: `{file}` + `{line}` + `{context}`.

Also determine the current AI runtime (Claude, Copilot, Gemini, etc.) from execution context. If the current runtime's instruction file does not exist and was not found above, add it to a `{to_create}` list.

If no existing instruction files found AND `{to_create}` is empty: print `No AI instruction files found — nothing to update.` and exit.

If existing files found but no flagged references AND `{to_create}` is empty: print `AI instruction files are already current — no legacy state-layout references detected.` listing files checked, and exit.

**Step AR2 — Dry-run**

```
AI RULES DRY RUN
================================================================
Existing files to update:
  File                                  Line   Current reference
  ─────────────────────────────────────────────────────────────
  CLAUDE.md                              42    sprint-status.yaml
  .github/copilot-instructions.md        17    _bmad-output/sprint-status.yaml

Files to create (current AI runtime):
  {file} — new section: PM state file layout

Files checked (no changes needed):
  {files_with_no_hits}
================================================================
{N} reference(s) to update across {M} existing file(s). {C} file(s) to create.
```

**Step AR3 — Confirm**

Ask: "Update {N} reference(s) in {M} file(s) and create {C} new file(s)?"

If no: print `Update cancelled — no changes made.` and exit.

**Step AR4 — Apply updates to existing files**

For each file in the findings list, read the full content. For each flagged reference, construct a contextually appropriate replacement:

- **Inline path** (e.g., `some/path/sprint-status.yaml`): replace the path with `{pm_state_root}` (rendered as the project's actual relative path, e.g. `docs/implementation-artifacts/state/`) and append ` (sharded state tree — one YAML file per epic/sprint/story)`.
- **Standalone keyword** (e.g., "reads sprint-status.yaml"): replace with a brief description: "the sharded state tree under `{pm_state_root}` — `active/epic-{nnn}/`, `planned/epic-{nnn}/`, `archived/epic-{nnn}/`, one YAML file per node".
- **Section or block** describing the state files: replace the entire description block with the state layout section from Step AR5 below, preserving surrounding format.

Read 3 lines of surrounding context before choosing the replacement strategy. Write the updated content to disk.

**Step AR5 — Create new file for current runtime**

For each file in `{to_create}`, create the file (and any parent directories, e.g. `.github/`) and write a minimal AI instruction section covering the PM state file layout:

````markdown
