# Epic Closure Report — E002: Reliable Installation, Build & Release Pipeline

**Goal:** Users can install this tool via `pip` or Docker and get a working, consistent result
every time, and maintainers can trust that tagging a release actually builds and publishes it.

**Final status:** Done. 1 sprint, 5 stories, all complete, no carry-over.

## Estimate vs actual

| Metric | Estimate (low–high) | Actual |
|---|---|---|
| man_hours | 43.62–49.57 | 12.0 (sprint total) |
| hitl_hours | 2.6–2.95 | 1.0 |
| elapsed_hours | 14.54–16.53 | 4.5 |
| tokens_k | 1024–1163 | N/A (runtime=other) |
| cost | $4.22–$4.79 | N/A |

Actuals came in well under the cold-start estimate, consistent with Epic 1 — no prior
calibration sample existed for this project when the plan was built.

## Sprint velocity summary

Single sprint (S01), 5/5 stories done, 0 carry-over. See
`sprint-01/closure/closure-report.md` for full per-story detail.

## Retrospective learnings

See `epic-closure/retrospective.md` — top item: real build+run verification (not just diff
review) is what caught both the dead base-image tag and the confuse/Python 3.14 break: this
class of defect is invisible to static review of a Dockerfile.

## Outstanding issues (by severity)

- HIGH: 0 open (1 found, fixed in-sprint: `BL-E002-001`)
- LOW: 0 open (1 process note, not a code defect: `BL-E002-002`)

## ADRs produced

None — all changes implement existing recorded decisions (ADR-0002, ADR-0004, ADR-0005)
rather than requiring a new one.
