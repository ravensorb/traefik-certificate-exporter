# Sync Step 04: Resolve

Communicate all responses in `{communication_language}`.

Consolidate what step-03 did into a final report. There is no separate field-level conflict
resolver here — `push` already resolves "which side wins" by construction (it always
overwrites the remote issue with current local content and stamps the hash), and `pull` only
ever moves a story forward to `done` when its issue closed. Nothing in step-03 leaves a
local/remote field disagreement for this step to adjudicate.

## 1. Handle `missing_local` (mapped, but local file gone)

If step-03 (`push` or `status`) reported any `missing_local` entries, they were already
reported there and were **not** touched — the mapping in `sync-state.yaml` and the remote
issue are both left exactly as they are. Re-list them here for visibility in the final
report. If the user confirms a deletion was intentional, the mapping can be cleared with:

```bash
python3 {skill-root}/scripts/sync-state.py {project-root} remove {bmad_key}
```

Only run `remove` on explicit user confirmation — never automatically, since it is
irreversible (no corresponding "undelete").

## 2. Timestamps

Nothing to do here separately — `push` already calls `update-hash`, which stamps
`last_synced_at` on every entry it touches at the point it touches it. There is no batch
timestamp pass at the end of the run.

## 3. Write sync report

Write `{project-root}/_bmad/sync-report-{iso_date}.md`:

- Mode run (`{sync_mode}`), platform (`{sync_platform}`), owner/repo, timestamp
- Items created / updated / status-synced (from step-03's push and/or pull sections)
- `missing_local` entries flagged this run (bmad_key, remote_url) and whether any were
  cleared via `remove`
- `sync-state.yaml` path, for reference

## 4. Output

```text
Step 04 complete — sync report: {project-root}/_bmad/sync-report-{iso_date}.md
```
