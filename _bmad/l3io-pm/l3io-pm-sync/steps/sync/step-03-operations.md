# Sync Step 03: Operations

Communicate all responses in `{communication_language}`.

Execute the sync operation specified by `{sync_mode}`. All three scripts do local
computation only — `detect-platform.py`, `drift-report.py`, and `sync-state.py` never make a
remote API call. Every remote GitHub operation (creating/editing an issue, reading its
state, checking auth) is performed by **you**, the agent, using GitHub MCP tools when
`{auth_method}` = `mcp`, or the `gh` CLI when `{auth_method}` = `gh-cli`.

## Mode: setup

1. Platform and auth are already confirmed by step-02 (`{sync_platform}`,
   `{platform_owner}`/`{platform_repo}`, `{auth_method}`).
2. Verify `_bmad/sync-state.yaml` is readable:
   ```bash
   python3 {skill-root}/scripts/sync-state.py {project-root} list
   ```
   An empty `[]` with no file on disk is a normal first run — `sync-state.py` creates the
   file lazily on the first `upsert` (during `push`). There is no separate "init" command;
   do not invent one.
3. Optional — create `_bmad/sync-config.yaml` if absent, from
   `{skill-root}/assets/sync-config-template.yaml`, pre-filling `github.owner` and
   `github.repo` from step-02's detection. Add it to `.gitignore` (the template header says
   it is project-scoped and not committed). This file is not read by any current script —
   it exists for future field-authority/label overrides and as the location
   `detect-platform.py` itself points to when platform detection fails — so treat this as
   best-effort, never blocking.
4. Report: platform, owner/repo, auth method confirmed usable, `sync-state.yaml` path
   (materializes on first push), `sync-config.yaml` path if created.

## Mode: push

1. Run the drift report:
   ```bash
   python3 {skill-root}/scripts/drift-report.py {project-root}
   ```
   Parse its three buckets: `unmapped_local`, `changed_local`, `missing_local`.

2. For each entry in `unmapped_local` (never pushed before):
   - **You** create a GitHub Issue for it — GitHub MCP tools if available, else:
     ```bash
     gh issue create --repo {platform_owner}/{platform_repo} --title "..." --body "..."
     ```
     Title/body/labels come from the story/sprint/epic/backlog content at `bmad_path`
     (or the node itself for epics/sprints, which have no file).
   - Record the mapping — build a JSON object with at least `bmad_key`, `bmad_type`,
     `bmad_path`, `remote_id` (the new issue number), `remote_url`, then:
     ```bash
     echo '<json>' | python3 {skill-root}/scripts/sync-state.py {project-root} upsert -
     ```
     `upsert` reads `-` from stdin, `@<file>` from a file, or a literal JSON string
     (prefer stdin/file to avoid shell-quoting problems). The only required field is
     `bmad_key`.
   - Stamp the hash so this entry drops out of `unmapped_local` next run:
     ```bash
     python3 {skill-root}/scripts/sync-state.py {project-root} update-hash {bmad_key} {current_hash}
     ```
     `{current_hash}` is the `current_hash` field the drift report gave this entry.

3. For each entry in `changed_local` (already mapped, local content hash moved):
   - **You** update the existing issue (`remote_id`/`remote_url` are on the drift entry) —
     GitHub MCP tools, else `gh issue edit {remote_id} --repo {platform_owner}/{platform_repo} ...`.
   - Then:
     ```bash
     python3 {skill-root}/scripts/sync-state.py {project-root} update-hash {bmad_key} {current_hash}
     ```

4. For each entry in `missing_local` (mapped, but the local file is gone): **do not** touch
   the mapping or the remote issue. Report each one by `bmad_key` and `remote_url` so the
   user can decide — the mapping is not silently dropped just because push mode is what
   noticed it.

5. Report: issues created (`unmapped_local` count), issues updated (`changed_local` count),
   missing mappings flagged (`missing_local` count, listed).

## Mode: pull

1. Enumerate mappings:
   ```bash
   python3 {skill-root}/scripts/sync-state.py {project-root} list
   ```
2. For each mapping with `bmad_type` = `story`, **you** fetch the issue's current state —
   GitHub MCP tools, else:
   ```bash
   gh issue view {remote_id} --repo {platform_owner}/{platform_repo} --json state,title,labels
   ```
3. Where the issue state is `CLOSED`, update the story through `pm-status.py` — never write
   state YAML directly:
   ```bash
   python3 {pm_status} set-status --state-root {pm_state_root} --story {bmad_key} --status done
   ```
   Skip stories already `done` locally (idempotent — no need to re-write).
4. Mappings with `bmad_type` in `sprint`/`epic`/`backlog` are enumerated and reported but not
   auto-transitioned in this mode — `pm-status.py set-status` addresses one story/sprint/epic
   node per call and there is no defined mapping from an issue's state to a
   sprint/epic/backlog status here; report them as informational.
5. Report: stories updated to `done` (count, listed), mappings that failed to resolve
   remotely (issue deleted/inaccessible), sprint/epic/backlog mappings seen but not acted on.

## Mode: sync

Run **push** (section above) in full, then **pull** (section above) in full. Collect both
reports and present them together — do not interleave; push's issue creation/updates should
land before pull re-reads issue state.

## Mode: status

1. Run the same drift report as push:
   ```bash
   python3 {skill-root}/scripts/drift-report.py {project-root}
   ```
2. Present all three buckets readably, without mutating anything:
   - `unmapped_local` — entities never pushed (would be created by `push`)
   - `changed_local` — mapped entities whose local content moved since last sync (would be
     updated by `push`)
   - `missing_local` — mapped entities whose local file is gone (report by `bmad_key` and
     `remote_url`; nothing removes these automatically — a confirmed-intentional deletion can
     be cleared manually with `python3 {skill-root}/scripts/sync-state.py {project-root} remove {bmad_key}`)

## Output

```text
Step 03 complete — mode: {sync_mode}, created: {N}, updated: {N}, missing: {N}
```
