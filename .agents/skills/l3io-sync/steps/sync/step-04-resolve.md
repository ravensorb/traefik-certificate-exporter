# Sync Step 04: Resolve

Communicate all responses in `{communication_language}`.

Consolidate what step-03 did into a final report. There is no separate field-level conflict
resolver here — `push` already resolves "which side wins" by construction (it always
overwrites the remote issue with current local content and stamps the hash), and `pull` only
ever moves a story forward to `done` when its issue closed as `COMPLETED`. Nothing in step-03 leaves a
local/remote field disagreement for this step to adjudicate.

## 1. Handle `missing_local` (mapped, but local file gone)

If step-03 (`push` or `status`) reported any `missing_local` entries, they were already
reported there and were **not** touched — the mapping in `sync-state.yaml` and the remote
issue are both left exactly as they are. Before treating any of them as a deletion, run the
re-key check below; what it does not claim is what remains.

**`push` already ran this**, at step-03 §2 — it has to, because step-03 creates issues and a
re-keyed story is in `unmapped_local` too. Do not run it twice: a `missing_local` list that
survived step-03's re-run of the drift report is already the residue. For `status` and `pull`,
which create nothing, here is the first and only place it runs.

### Re-keyed, not deleted

`/l3io-plan reorg` moves planned stories between sprints, which **re-keys** them
(`E007-S02-004` becomes e.g. `E003-S01-005`). The old key's mapping then names a node that
no longer resolves, and the new key was never pushed — so the one story appears in the drift
report **twice**, as `missing_local` and as `unmapped_local`. Left alone, that produces a
duplicate remote issue plus an orphaned one, not just a dangling link.

Every re-parented node carries `previous_keys`: an ordered list, oldest first, appended to on
each move. For each `missing_local` entry:

1. Look for a node whose `previous_keys` **contains** the entry's `bmad_key`. Match **any**
   element, not only the last — a story reorganised twice has two hops, and a mapping made
   before the first move would be missed by a last-only check. The nodes come from:
   ```bash
   uv run {pm_status} dump-plan --state-root {pm_state_root}
   ```
   Read each story's `previous_keys` from that JSON. A story whose record carries no
   `previous_keys` was never moved.
2. If exactly one node matches, **re-point** the mapping to that node's current `key` instead
   of clearing it: read the old entry with `sync-state.py get {old_key}`, then write it back
   under the new key with every remote field (`remote_id`, `remote_url`, ...) unchanged and
   `bmad_path` set to the node's current path:
   ```bash
   echo '<json>' | uv run {skill-root}/scripts/sync-state.py {project-root} upsert -
   uv run {skill-root}/scripts/sync-state.py {project-root} remove {old_key}
   ```
   Carry `last_synced_hash` across unchanged, so the next drift report compares the issue
   against what was actually last pushed: if the re-key also changed the story's content the
   entry lands in `changed_local` and the existing issue is **updated**, and if it did not,
   nothing is pushed. Either way no second issue is created. Never `remove` the old mapping
   before the new one is written — a crash between the two would lose the remote link
   entirely, which is the one outcome worse than a duplicate.
3. If **more than one** node matches, or none does, do not guess — leave the entry as an
   ordinary `missing_local` and say so in the report.

This reconciles on BMad's own key and never inspects the remote, so it is identical for every
sync platform. Record each re-point in the report (section 3) as `old_key -> new_key`.

### Genuinely missing

Whatever the check did not match is a candidate deletion. Re-list those here for visibility
in the final report. If the user confirms a deletion was intentional, the mapping can be
cleared with:

```bash
uv run {skill-root}/scripts/sync-state.py {project-root} remove {bmad_key}
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
- Mappings re-pointed after a re-key (`old_key -> new_key`, remote_url)
- `missing_local` entries flagged this run (bmad_key, remote_url) and whether any were
  cleared via `remove`
- `sync-state.yaml` path, for reference

## 4. Output

```text
Step 04 complete — sync report: {project-root}/_bmad/sync-report-{iso_date}.md
```
