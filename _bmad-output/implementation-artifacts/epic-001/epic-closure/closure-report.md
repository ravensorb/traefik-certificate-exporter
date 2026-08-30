# Epic Closure Report — E001: Trustworthy Certificate Export Core

**Goal:** Users can trust that every certificate this tool exports is correct, that a
misconfiguration fails loudly instead of silently, and that secrets are never exposed in
logs — and future changes cannot silently regress any of this because the whole export
surface is now covered by automated tests.

**Final status:** Done. 1 sprint, 3 stories, all complete, no carry-over.

## Estimate vs actual

| Metric | Estimate (low–high) | Actual |
|---|---|---|
| man_hours | 19.39–22.03 | 9.5 (sprint) — see note below |
| hitl_hours | 1.21–1.38 | 0.7 |
| elapsed_hours | 6.46–7.34 | 2.6 |
| tokens_k | 455–517 | N/A (runtime=other, not observable) |
| cost | $1.88–$2.14 | N/A |

Note: actual man-hours (9.5) came in well under the cold-start estimate's low bound
(19.39) — the estimate was priced from generic classification bands with no prior calibration
sample for this project; now that real actuals exist, future estimates will calibrate toward
observed reality rather than the cold-start prior.

## Sprint velocity summary

Single sprint (S01), 3/3 stories done, 0 carry-over. See
`sprint-01/closure/closure-report.md` for full per-story detail.

## Retrospective learnings

See `epic-closure/retrospective.md` (this directory) for the full writeup — top items:
import-time argv parsing is a recurring untestability shape across the module-level
singletons, `confuse`'s "later source wins" precedence model needs explicit attention on any
future reordering, and fixture-driven regression tests found a real functional bug immediately.

## Outstanding issues (by severity)

- MEDIUM: 0 open (3 found, fixed in-sprint: `BL-E001-001`, `BL-E001-002`, `BL-E001-003` —
  the latter two downgraded from Critical/High after the impact was scoped more precisely:
  neither ever affected certificate export to disk, only the optional Docker
  restart-on-label feature)
- RETRACTED: 1 (`BL-E001-004` — a "config precedence" change based on the agent's own
  undocumented assumption, not a confirmed defect; reverted, not shipped)
- LOW: 2 open, deferred (`BL-E001-005`, `BL-E001-006`)

## ADRs produced

None — no architectural decision was contested; all fixes were straightforward corrections
consistent with existing recorded decisions.
