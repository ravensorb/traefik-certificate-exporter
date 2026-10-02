### 4. Build health snapshot

Report to user:

**Active epics** (from `{pm_state_root}/active/epic-*/epic.yaml`):
- List each epic: key, title, current sprint, sprint status
- Flag stale locks: if `_lock.claimed_at` is older than `_lock.ttl_minutes`, mark as ⚠️ STALE LOCK

**Planned epics** (from `{pm_state_root}/planned/epic-*/epic.yaml`):
- Count them, and list any whose `depends_on` names an epic that is not yet `done` (those
  are blocked, not merely waiting). Every epic under `planned/` has `status: backlog` —
  that is the only status `pm-status.py` accepts there — so there is no status breakdown
  to print.

**Open issues** (from `{pm_issues_file}`):
- Count open items by severity (Critical, High, Medium, Low), split into untriaged (`status`
  backlog) and scheduled, and note how many have an archived origin (`origin_archived`). With
  the `cat` fallback, every item under `backlog:` is open. If any untriaged item is Critical or
  High, recommend `/l3io-plan` (backlog intake) or `/l3io-doctor triage`. Count
  `spec-change` items (unconfirmed spec edits) and `spec-proposal` items (proposed PRD/UX/epic
  changes) separately, by their `kind` field — with the `cat` fallback read each item's `kind:`;
  an item without one is a defect. If any are open, recommend `/l3io-doctor triage` (its
  spec pass confirms or rejects them).

**Plan status** (from `plan-output-meta.yaml`):
- `readiness`, `generated` timestamp, and the phase count — read `phase_count` when present;
  when it is absent the pointer predates that field, so fall back to the length of its legacy
  `phases:` list. Current pointers carry `phase_count` and no `phases:` list; do not read
  anything else per-phase from this file, and never open the snapshot just to count phases.
- If absent: note "No plan found"

