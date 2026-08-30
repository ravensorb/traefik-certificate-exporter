# Epic 3 — Closure Report

**Epic:** E003 — Predictable, Documented Configuration
**Sprints:** 1 (S01), 2 stories, no carry-over

## Stories delivered

| Story | Title | Outcome |
|---|---|---|
| E003-S01-001 | Fix Domain Include/Exclude Across All Config Surfaces | Root cause was `confuse`'s shallow dict merge across sources (not the assumed missing validation check) plus env vars never being comma-split into a list. Fixed both; added explicit mutual-exclusivity validation across all three surfaces (CLI/env/config file). |
| E003-S01-002 | Add and Document a PKCS12 Passphrase Setting | Added `--pkcs12-passphrase` CLI flag; documented across README.md, docker/README.md, config.sample.yml, config_default.yaml. Redaction (Epic 1) already covers it with no code change. |

## Evidence

- `poetry run pytest`: 36/36 passed (30 carried over from Epic 1/2 + 6 new: 5 domain
  include/exclude tests, 1 PKCS12 CLI flag test).
- `docker/README.md`'s `FIXME` (GitHub #5) removed; PRD backlog items #2, #3, #6 corrected
  in `docs/operational.md` (all now fixed, previously described as still-open).
- Live repro of the reported bug (`poetry run python3` against the real `SettingsManager`)
  performed before writing the fix, confirming the exact `KeyError`/dropped-key symptom
  described in GitHub #5.

## Deviation from plan

The story's stated root cause ("CLI enforces mutual exclusivity via argparse but env-var/
config-file paths don't") was incomplete — the dominant bug was actually a `confuse`
dict-merge gap that could crash the app outright (`KeyError`) when only one of
include/exclude was set anywhere. The mutual-exclusivity gap the story described was real
but secondary. Both are fixed; acceptance criteria are met as written.
