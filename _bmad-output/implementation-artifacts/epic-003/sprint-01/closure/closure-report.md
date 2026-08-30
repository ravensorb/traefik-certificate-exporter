# Closure Report — E003 / Sprint S01

## Stories done: 2/2

| Story | Notes |
|---|---|
| E003-S01-001 | Real root cause: `confuse`'s nested-dict `.get()` drops sibling keys across sources; also env-var comma-split was missing. Fixed both, plus explicit mutual-exclusivity validation across CLI/env/config file. |
| E003-S01-002 | `--pkcs12-passphrase` CLI flag added; documented in README.md, docker/README.md, config.sample.yml, config_default.yaml. |

## Issues resolved (fixed in-sprint)

- None logged as backlog issues — both defects were reproduced and fixed directly within
  the sprint.

## Phases run vs skipped

| Phase | Ran? |
|---|---|
| Retrospective | Ran |
| Clean release review | Ran — no dead code, docker/README.md's stale FIXME removed, docs/operational.md's 3 stale "known gap" notes corrected |
| Adversarial analysis | Ran — no CRITICAL/HIGH findings |
| Red team | Skipped — no new attack surface or secrets introduced |
| UX review | Skipped — not installed, no UI-facing stories |
| Sprint architectural drift | Ran — consistent with existing settings-loading pattern, no new ADR needed |
| Issue triage | Ran — 0 new deferred issues |

## Test evidence

- `poetry run pytest` — 36/36 passed (30 carried over + 6 new)
- Live repro of GitHub #5's reported symptom against the real `SettingsManager`, before
  and after the fix, confirming the `KeyError` root cause and its resolution
- `pre-commit run ruff-check --files <touched files>` — 3 pre-existing findings unrelated
  to this epic's diff (EXE001 shebang, RUF012 mutable default), confirmed via `git diff`
  not introduced by this epic's changes
