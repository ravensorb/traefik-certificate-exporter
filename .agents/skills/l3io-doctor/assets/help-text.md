l3io-doctor — Project State Diagnostics & Utilities
========================================================
Usage: /l3io-doctor [command]

Diagnostic (read-only)
  (no argument)      Project health check — scan and propose all needed actions
  check / status     Read-only health check — report findings, no changes
  stats              Plan-aware progress dashboard — phase/epic/sprint/story + backlog
  backlog / issues   Aliases for stats; always print the per-item backlog table
  check-deps         Verify BMad skill dependencies resolve in this project
  check-pm-status    Verify installed pm-status.py matches this doctor's module_version

One-time migrations (run in this order)
  migrate-schema     (legacy-only) Add missing fields to a legacy flat sprint-status.yaml
  split-status       (legacy-only) Split flat sprint-status.yaml into the 3-file form
  migrate-state      Migrate either legacy layout to the sharded state tree  <- the one
                     that makes a legacy project usable by the PM skills again
  bootstrap-state    Create sharded state nodes from existing story .md artifact files
                     (for projects using the legacy bmad-create-story workflow without l3io-plan)
  migrate-adrs       Move ADRs from epic-*/arch/ to docs/adr/, the one ADR home

Ongoing maintenance (safe to repeat)
  reconcile-status   (legacy-only) Fix misplaced epics, nested backlogs, stale items
  sort-status        Validate zero-padded naming (epic-{nnn}/, sprint-{nn}/, story keys)
  clean-layout       Reorganize flat artifact files into epic/sprint folder structure
                     (alias: layout-cleanup, deprecated in 3.1.4)
  redrive            Rebuild calibration scope/fix samples from the story nodes on disk
  triage             Audit the issues backlog and resolve findings already fixed

Source & external sync
  harvest-debt       Sweep source for bmad-defer: markers and harvest into backlog
  update-ai-rules    Update AI instruction files to describe the sharded state tree

Setup & housekeeping
  setup              Register l3io-util module config for this project
  clean-legacy       Remove .legacy/.v1 migration backup files and the state.legacy/ and
                     migration-backup/ backup directories after confirmation

Run without arguments to let the health check decide what's needed.
