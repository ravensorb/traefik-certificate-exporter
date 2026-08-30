# Closure Report — E001 / Sprint S01

## Stories done: 3/3

| Story | Estimate (man-hrs) | Actual (man-hrs, counterfactual) | Notes |
|---|---|---|---|
| E001-S01-001 | 1.5–2.0 (simple band) | 1.0 | Redaction helper + 6 tests |
| E001-S01-002 | 1.5–2.0 (simple band) | 1.0 | Null-path fix + testable helper + 6 tests |
| E001-S01-003 | 5.0–6.0 (standard band) | 6.0 | Full pytest suite stood up; surfaced 3 additional defects beyond its own listed scope |

## Issues resolved (fixed in-sprint, not deferred)

- `BL-E001-001` — MEDIUM — import-time argv parsing crash (`cli_args.py`)
- `BL-E001-002` — MEDIUM — `__exportCertificate` missing `return names` (scope corrected: only affects the optional Docker restart-on-label feature, not certificate export to disk)
- `BL-E001-003` — MEDIUM — multi-resolver `append` vs `extend` nesting bug (same scope note as above)

## Issues retracted

- `BL-E001-004` — a "config precedence" fix was reverted after the maintainer confirmed the
  original order (`CLI > env var > config file > packaged default`) was correct and already
  working in production. The "documented precedence" it was checked against had been written
  by the agent itself earlier in this session, not confirmed with the maintainer first. See
  the full account in `state/issues.yaml` and the epic retrospective.

## Issues deferred

- `BL-E001-005` — LOW — redaction regex pattern coverage
- `BL-E001-006` — LOW — `parse_known_args` silently swallows unrecognized CLI args in production

## Phases run vs skipped

| Phase | Ran? |
|---|---|
| Retrospective | Ran |
| Clean release review | Ran (merged with adversarial, one pass) |
| Adversarial analysis | Ran |
| Red team | Ran (lightweight — no unredacted dump path found; no new attack surface) |
| UX review | Skipped — not installed, no UI-facing stories |
| Sprint architectural drift | Ran — no BLOCKER/MAJOR, no new ADR needed |
| Issue triage | Ran — 2 LOW findings deferred above |

## Test evidence

`poetry run pytest` — 30/30 passed (0.94s). Suite covers: secret redaction (6), null-path
handling (6), ACME v1/v2 parsing (8), Docker restart mocking (6), config precedence (4, now
asserting CLI > env var > config file > packaged default).
