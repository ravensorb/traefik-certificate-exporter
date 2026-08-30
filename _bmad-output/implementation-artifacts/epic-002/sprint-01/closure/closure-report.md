# Closure Report — E002 / Sprint S01

## Stories done: 5/5

| Story | Notes |
|---|---|
| E002-S01-001 | `cryptography` declared as explicit dependency |
| E002-S01-002 | `poetry` → dev deps; Dockerfile rebuilt as multi-stage `poetry install --only main` |
| E002-S01-003 | Base image `3.19` (dead at registry) → `3.24`, digest-pinned |
| E002-S01-004 | `build.yaml` rewritten to job-level reusable workflows; `actionlint` clean |
| E002-S01-005 | `ACT` env var branch removed; runner-agnostic CA cert import |

## Issues resolved (fixed in-sprint)

- `BL-E002-001` — HIGH — `confuse` 2.0.1 incompatible with Python 3.14 (Alpine 3.24), fixed via update to 2.2.1

## Process incidents (not shipped defects, recorded for transparency)

- `BL-E002-002` — LOW — `pre-commit --all-files` scope-creep incident and recovery (see retrospective.md)

## Phases run vs skipped

| Phase | Ran? |
|---|---|
| Retrospective | Ran |
| Clean release review | Ran — no dead code, no secrets committed, old hand-maintained pip list fully removed |
| Adversarial analysis | Ran — no CRITICAL/HIGH findings; multi-stage build correctly excludes build toolchain (gcc, musl-dev) from final image |
| Red team | Ran (lightweight) — CA cert action is a third-party action already vetted in guidelines §6; no secrets hardcoded, sourced via `secrets.CI_CA_CERTIFICATE` |
| UX review | Skipped — not installed, no UI-facing stories |
| Sprint architectural drift | Ran — consistent with ADR-0002, ADR-0004, ADR-0005; no new ADR needed |
| Issue triage | Ran — 0 new deferred issues (1 process note only) |

## Test evidence

- `poetry run pytest` — 30/30 passed
- `docker build -f docker/Dockerfile -t traefik-certificate-exporter:test .` — succeeds
- `docker run --rm traefik-certificate-exporter:test traefik-certificate-exporter --help` —
  runs end-to-end: loads config, exports, enters watch mode
- `pre-commit run actionlint --all-files` — clean
- `pre-commit run gitleaks --all-files` — clean
- `pre-commit run poetry-lock --all-files` — clean (also fixed: `poetry lock --check` → `poetry check --lock` for Poetry 2.x)
